from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from common.context import RunContext, utc_now
from common.hashing import canonical_json, file_hash, sha256_text, short_hash
from common.io import read_jsonl, write_jsonl

from facet_terminal.input_adapters import adapt_record
from facet_terminal.pipeline import resolve_path, stage_cfg, write_stage_report


def convert_input_record(
    record: dict[str, Any], index: int, source_name: str, source: dict[str, Any]
) -> dict[str, Any]:
    adapted = adapt_record(record, source)
    skill_ids = adapted["skill_ids"]
    pair_id = str(adapted["pair_id"] or "pair_" + short_hash(canonical_json(record), 16))
    task_id = "task_" + short_hash(pair_id + "\n" + "|".join(skill_ids), 12)
    return {
        "schema_version": "facet_terminal_input",
        "source": source_name,
        "source_index": index,
        "task_id": task_id,
        "pair_id": pair_id,
        "pair_size": 2,
        "skill_ids": skill_ids,
        "skill_summaries": adapted["skill_summaries"],
        "scenario_texts": adapted["scenario_texts"],
        "quality": adapted["quality"],
        "raw_hash": sha256_text(canonical_json(record)),
    }


def run(ctx: RunContext, args: argparse.Namespace) -> None:
    stage = "convert_input"
    started = utc_now()
    cfg = stage_cfg(ctx, stage)
    output_path = ctx.path(str(cfg.get("output_jsonl", "artifacts/facet_terminal/input_units.jsonl")))
    input_run_dir = resolve_path(ctx, str(cfg.get("input_run_dir") or "."))
    sources = cfg.get("sources") or [{"path": "skill_pairs.jsonl", "format": "skill_pair_jsonl"}]
    if not isinstance(sources, list) or not sources:
        raise ValueError("convert_input sources must be a non-empty list")
    converted: list[dict[str, Any]] = []
    source_counts: dict[str, int] = {}
    selected_source = None
    for source in sources:
        rel = str(source["path"])
        path = input_run_dir / rel
        if not path.exists():
            source_counts[rel] = 0
            continue
        records = read_jsonl(path)
        source_counts[rel] = len(records)
        converted = [
            convert_input_record(record, index, rel, source)
            for index, record in enumerate(records, start=1)
        ]
        selected_source = rel
        if converted:
            break
    if not converted:
        raise ValueError(f"no adaptable input units found under {input_run_dir}; source_counts={source_counts}")
    write_jsonl(output_path, converted)
    summary = {
        "input_run_dir": str(input_run_dir),
        "selected_source": selected_source,
        "source_counts": source_counts,
        "converted_count": len(converted),
    }
    write_stage_report(
        ctx,
        stage,
        started,
        {"input_run_dir": str(input_run_dir), "sources": sources},
        {"input_units": {"path": str(output_path.relative_to(ctx.run_dir)), "records": len(converted), "hash": file_hash(output_path)}},
        summary,
        cfg,
    )
