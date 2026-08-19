from __future__ import annotations

import argparse
from collections import Counter

from common.context import RunContext, utc_now
from common.hashing import file_hash
from common.io import read_jsonl, write_json, write_text

from facet_terminal.pipeline import stage_cfg, write_stage_report


def task_ids(rows: list[dict], *, nested_key: str, status: str) -> set[str]:
    ids: set[str] = set()
    for row in rows:
        nested = row.get(nested_key, {})
        if not isinstance(nested, dict) or nested.get("status") != status:
            continue
        task_id = str(row.get("task_id") or "").strip()
        if task_id:
            ids.add(task_id)
    return ids


def run(ctx: RunContext, args: argparse.Namespace) -> None:
    stage = "report"
    started = utc_now()
    cfg = stage_cfg(ctx, stage)
    paths = {
        "selected": ctx.path(str(cfg.get("selected_jsonl", "artifacts/facet_terminal/selected_units.jsonl"))),
        "planned": ctx.path(str(cfg.get("planned_jsonl", "artifacts/facet_terminal/planned_units.jsonl"))),
        "instruction_ref": ctx.path(str(cfg.get("instruction_ref_jsonl", "artifacts/facet_terminal/instruction_ref_units.jsonl"))),
        "env_build": ctx.path(str(cfg.get("env_build_jsonl", "artifacts/facet_terminal/env_build_units.jsonl"))),
        "env_ready": ctx.path(str(cfg.get("env_ready_jsonl", "artifacts/facet_terminal/env_ready_units.jsonl"))),
        "instruction": ctx.path(str(cfg.get("instruction_jsonl", "artifacts/facet_terminal/instruction_units.jsonl"))),
        "tests": ctx.path(str(cfg.get("tests_jsonl", "artifacts/facet_terminal/test_units.jsonl"))),
        "solution": ctx.path(str(cfg.get("solution_jsonl", "artifacts/facet_terminal/solution_units.jsonl"))),
        "validation": ctx.path(str(cfg.get("validation_jsonl", "artifacts/facet_terminal/validation_units.jsonl"))),
        "repair": ctx.path(str(cfg.get("repair_jsonl", "artifacts/facet_terminal/repair_units.jsonl"))),
    }
    data = {name: read_jsonl(path) for name, path in paths.items()}
    validation_statuses = Counter(row.get("validation", {}).get("status", "unknown") for row in data["validation"])
    failure_types = Counter(row.get("validation", {}).get("failure_type", "unknown") for row in data["validation"])
    repair_statuses = Counter(row.get("repair", {}).get("status", "unknown") for row in data["repair"])
    initial_validated_ids = task_ids(data["validation"], nested_key="validation", status="validated")
    repaired_ids = task_ids(data["repair"], nested_key="repair", status="repaired")
    final_accepted_ids = initial_validated_ids | repaired_ids
    summary = {
        "selected": len(data["selected"]),
        "plan_ready": len(data["planned"]),
        "instruction_ref_ready": len(data["instruction_ref"]),
        "env_build_ready": len(data["env_build"]),
        "env_ready": len(data["env_ready"]),
        "instruction_ready": len(data["instruction"]),
        "test_ready": len(data["tests"]),
        "solution_ready": len(data["solution"]),
        "initial_validated": len(initial_validated_ids),
        "validation_failed": validation_statuses.get("failed", 0),
        "repair_attempted": len(data["repair"]),
        "repaired": len(repaired_ids),
        "repair_unrepaired": repair_statuses.get("unrepaired", 0),
        "repair_infeasible": repair_statuses.get("infeasible", 0),
        "final_accepted": len(final_accepted_ids),
        "failed": max(0, len(data["selected"]) - len(final_accepted_ids)),
        "failure_distribution": dict(failure_types),
    }
    output_json = ctx.path(str(cfg.get("output_json", "reports/facet_terminal_summary.json")))
    output_md = ctx.path(str(cfg.get("output_md", "reports/facet_terminal_summary.md")))
    write_json(output_json, summary)
    write_text(
        output_md,
        "# FACET-Terminal Summary\n\n"
        + "\n".join(f"- {key}: {value}" for key, value in summary.items())
        + "\n",
    )
    write_stage_report(
        ctx,
        stage,
        started,
        {name: {"path": str(path.relative_to(ctx.run_dir)), "hash": file_hash(path) if path.exists() else None} for name, path in paths.items()},
        {"summary_json": {"path": str(output_json.relative_to(ctx.run_dir)), "hash": file_hash(output_json)}},
        summary,
        cfg,
    )
