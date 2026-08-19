from __future__ import annotations

import argparse
import json

from common.context import RunContext, utc_now
from common.hashing import file_hash
from common.io import read_jsonl, write_jsonl

from facet_terminal.pipeline import ArtifactWriter, record_event, stage_cfg, task_root, write_stage_report


def _blueprint(unit: dict) -> dict:
    plan = unit.get("task_plan", {})
    return unit.get("task_blueprint") or plan.get("code_task_blueprint") or plan.get("task_blueprint") or {}


def _output_path(blueprint: dict, root: str) -> str:
    output_model = blueprint.get("expected_behavior", {}).get("output_model", {})
    fmt = str(output_model.get("format") or "json").lower()
    ext_by_format = {"json": "json", "jsonl": "jsonl", "csv": "csv", "txt": "txt", "yaml": "yaml", "toml": "toml"}
    return f"{root}/output/result.{ext_by_format.get(fmt, 'txt')}"


def task_toml(task_id: str, unit: dict, root: str) -> str:
    blueprint = _blueprint(unit)
    skill_tags = blueprint.get("skill_usage", {}).get("primary_skills", []) or unit.get("skill_summaries", [])
    tags = [str(tag).replace('"', "") for tag in (unit.get("task_plan", {}).get("tags", []) or skill_tags)[:8]]
    difficulty = str(blueprint.get("generation_constraints", {}).get("difficulty") or "medium")
    tag_text = "".join(f" {json.dumps(tag)}," for tag in tags)
    return (
        'version = "1.0"\n\n'
        "[task]\n"
        'name = "facet-terminal/task"\n'
        "authors = []\n"
        "keywords = []\n\n"
        "[metadata]\n"
        'author_name = "FACET-Terminal"\n'
        f'difficulty = "{difficulty}"\n'
        'category = "terminal_task_synthesis"\n'
        f"tags = [{tag_text}]\n"
        f'task_name = "{task_id}"\n'
        f'workdir = "{root}"\n\n'
        "[verifier]\n"
        "timeout_sec = 120.0\n\n"
        "[agent]\n"
        "timeout_sec = 120.0\n\n"
        "[environment]\n"
        "build_timeout_sec = 600.0\n"
        "cpus = 1\n"
        "memory_mb = 2048\n"
        "storage_mb = 10240\n"
        "gpus = 0\n"
        "allow_internet = true\n"
        "mcp_servers = []\n\n"
        "[verifier.env]\n\n"
        "[solution.env]\n"
    )


def run(ctx: RunContext, args: argparse.Namespace) -> None:
    stage = "skeleton"
    started = utc_now()
    cfg = stage_cfg(ctx, stage)
    root = task_root(cfg)
    input_path = ctx.path(str(cfg.get("input_jsonl", "artifacts/facet_terminal/planned_units.jsonl")))
    output_path = ctx.path(str(cfg.get("output_jsonl", "artifacts/facet_terminal/skeleton_units.jsonl")))
    units = read_jsonl(input_path)
    writer = ArtifactWriter(ctx, stage)
    rows = []
    for unit in units:
        task_id = str(unit["task_id"])
        blueprint = _blueprint(unit)
        expected = _output_path(blueprint, root)
        writer.write_text(task_id, "task.toml", task_toml(task_id, unit, root))
        writer.write_json(
            task_id,
            "manifest.json",
            {
                "task_id": task_id,
                "pair_id": unit.get("pair_id"),
                "schema_version": "facet_terminal_candidate",
                "skill_pair": unit.get("skill_ids", []),
                "layout": "harbor_task_candidate",
                "blueprint_output_path": expected,
            },
        )
        row = dict(unit)
        row["task_dir"] = f"artifacts/facet_terminal/tasks/candidates/{task_id}"
        rows.append(row)
        record_event(ctx, task_id, stage, "skeleton_ready")
    write_jsonl(output_path, rows)
    summary = {"input_count": len(units), "skeleton_count": len(rows)}
    write_stage_report(
        ctx,
        stage,
        started,
        {"planned_units": {"path": str(input_path.relative_to(ctx.run_dir)), "hash": file_hash(input_path)}},
        {"skeleton_units": {"path": str(output_path.relative_to(ctx.run_dir)), "records": len(rows), "hash": file_hash(output_path)}},
        summary,
        cfg,
    )
