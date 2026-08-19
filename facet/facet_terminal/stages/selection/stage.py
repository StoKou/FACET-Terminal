from __future__ import annotations

import argparse
from collections import Counter
import random
from typing import Any

from common.context import RunContext, utc_now
from common.hashing import canonical_json, file_hash, sha256_text
from common.io import read_jsonl, write_jsonl

from facet_terminal.pipeline import stage_cfg, write_stage_report


def _dedupe_value(unit: dict[str, Any], key_name: str) -> str:
    if key_name == "skill_set":
        return "|".join(sorted(map(str, unit.get("skill_ids", []))))
    if key_name == "pair_id":
        return str(unit.get("pair_id"))
    if key_name == "none":
        return ""
    return sha256_text(canonical_json(unit.get(key_name)))


def run(ctx: RunContext, args: argparse.Namespace) -> None:
    stage = "selection"
    started = utc_now()
    cfg = stage_cfg(ctx, stage)
    input_path = ctx.path(str(cfg.get("input_jsonl", "artifacts/facet_terminal/input_units.jsonl")))
    output_path = ctx.path(str(cfg.get("output_jsonl", "artifacts/facet_terminal/selected_units.jsonl")))
    rejected_path = ctx.path(str(cfg.get("rejected_jsonl", "artifacts/facet_terminal/rejected_units.jsonl")))
    units = read_jsonl(input_path)
    max_input_count = cfg.get("max_input_count")
    if max_input_count is not None:
        units = units[: int(max_input_count)]
    target_count = int(args.limit or cfg.get("target_count", len(units)))
    accepted_only = bool(cfg.get("accepted_only", True))
    require_scenarios = bool(cfg.get("require_non_empty_scenario_texts", True))
    dedupe_key = str(cfg.get("dedupe_key", "skill_set"))
    sort_by = str(cfg.get("sort_by", "source_index"))
    sampling_strategy = str(cfg.get("sampling_strategy", "first"))
    seed = int(cfg.get("seed", 42))
    selected: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    seen: set[str] = set()
    for unit in units:
        reasons: list[str] = []
        quality = unit.get("quality", {}) or {}
        if accepted_only and quality and quality.get("overall_status") not in {None, "", "ACCEPTED"}:
            reasons.append("not_accepted")
        if len(unit.get("skill_ids") or []) != 2:
            reasons.append("not_a_skill_pair")
        if require_scenarios and not unit.get("scenario_texts"):
            reasons.append("scenario_texts_empty")
        key = _dedupe_value(unit, dedupe_key)
        if key and key in seen:
            reasons.append("duplicate")
        if reasons:
            row = dict(unit)
            row["reject_reasons"] = reasons
            rejected.append(row)
            continue
        if key:
            seen.add(key)
        selected.append(unit)
    if sort_by == "random" or sampling_strategy == "random":
        random.Random(seed).shuffle(selected)
    else:
        selected.sort(key=lambda item: int(item.get("source_index", 0)))
    selected = selected[:target_count]
    for index, unit in enumerate(selected, start=1):
        unit["selected_index"] = index
        unit["task_name"] = f"task_{index:06d}"
        unit["task_id"] = unit["task_name"]
    write_jsonl(output_path, selected)
    write_jsonl(rejected_path, rejected)
    summary = {
        "input_count": len(units),
        "selected_count": len(selected),
        "rejected_count": len(rejected),
        "target_count": target_count,
        "rejection_counts": dict(Counter(reason for row in rejected for reason in row.get("reject_reasons", []))),
    }
    write_stage_report(
        ctx,
        stage,
        started,
        {"input_units": {"path": str(input_path.relative_to(ctx.run_dir)), "hash": file_hash(input_path)}},
        {"selected_units": {"path": str(output_path.relative_to(ctx.run_dir)), "records": len(selected), "hash": file_hash(output_path)}},
        summary,
        cfg,
    )
