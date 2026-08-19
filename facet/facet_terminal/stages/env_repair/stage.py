from __future__ import annotations

import argparse
from collections import Counter

from common.context import RunContext, utc_now
from common.hashing import file_hash
from common.io import read_json, read_jsonl, write_json, write_jsonl
from common.model_pool import ModelClient

from facet_terminal.pipeline import record_event, stage_cfg, stage_report_dir, worker_count, write_stage_report
from facet_terminal.scheduler import run_batched
from facet_terminal.stages.env_build.stage import env_build_one


def env_report(ctx: RunContext, task_id: str) -> dict:
    path = stage_report_dir(ctx, "env_build") / f"{task_id}.json"
    return read_json(path) if path.exists() else {}


def env_repair_one(ctx: RunContext, env_cfg: dict, model_client: ModelClient | None, unit: dict) -> dict:
    task_id = str(unit["task_id"])
    before = env_report(ctx, task_id)
    repair_unit = dict(unit)
    if before.get("failure_type"):
        repair_unit["env_repair_hint"] = {
            "previous_status": before.get("status", "missing"),
            "previous_failure_type": before.get("failure_type"),
            "previous_error": before.get("error"),
        }
    result = env_build_one(ctx, env_cfg, model_client, repair_unit)
    status = "env_repaired" if result.get("status") == "env_build_ready" else "env_repair_failed"
    report = {
        "task_id": task_id,
        "status": status,
        "previous_status": before.get("status", "missing"),
        "previous_failure_type": before.get("failure_type"),
        "env_build_status": result.get("status"),
    }
    write_json(stage_report_dir(ctx, "env_repair") / f"{task_id}.json", report)
    record_event(ctx, task_id, "env_repair", status, previous_failure_type=report["previous_failure_type"])
    result_unit = result.get("unit", unit)
    if isinstance(result_unit, dict):
        result_unit = dict(result_unit)
        result_unit.pop("env_repair_hint", None)
    return {"status": status, "task_id": task_id, "unit": result_unit}


def run(ctx: RunContext, args: argparse.Namespace) -> None:
    stage = "env_repair"
    started = utc_now()
    cfg = stage_cfg(ctx, stage)
    env_cfg = stage_cfg(ctx, "env_build")
    input_path = ctx.path(str(cfg.get("input_jsonl", "artifacts/facet_terminal/instruction_ref_units.jsonl")))
    env_build_path = ctx.path(str(cfg.get("env_build_jsonl", "artifacts/facet_terminal/env_build_units.jsonl")))
    output_path = ctx.path(str(cfg.get("output_jsonl", "artifacts/facet_terminal/env_ready_units.jsonl")))
    units = read_jsonl(input_path)
    if args.limit:
        units = units[: args.limit]
    ready_units = read_jsonl(env_build_path) if env_build_path.exists() else []
    ready_by_task = {str(unit["task_id"]): unit for unit in ready_units}
    pass_through_count = sum(1 for unit in units if str(unit["task_id"]) in ready_by_task)
    targets = [unit for unit in units if str(unit["task_id"]) not in ready_by_task]
    if not bool(cfg.get("enabled", True)):
        merged = [ready_by_task[str(unit["task_id"])] for unit in units if str(unit["task_id"]) in ready_by_task]
        write_jsonl(output_path, merged)
        write_stage_report(
            ctx,
            stage,
            started,
            {"instruction_ref_units": {"path": str(input_path.relative_to(ctx.run_dir)), "hash": file_hash(input_path)}},
            {"env_ready_units": {"path": str(output_path.relative_to(ctx.run_dir)), "records": len(merged), "hash": file_hash(output_path)}},
            {"enabled": False, "input_count": len(units), "pass_through": len(merged), "repair_targets": len(targets)},
            cfg,
        )
        return
    model_client = ModelClient(ctx) if str(env_cfg.get("mode", "llm")) != "template" else None
    results = run_batched(
        "facet_terminal_env_repair:repair",
        targets,
        worker_count(ctx, stage, cfg, args.workers),
        int(cfg.get("batch_size", 2)),
        int(cfg.get("max_inflight_batches", 1)),
        lambda unit: env_repair_one(ctx, env_cfg, model_client, unit),
    )
    repaired_by_task = {row["task_id"]: row["unit"] for row in results if row.get("status") == "env_repaired"}
    merged = []
    for unit in units:
        task_id = str(unit["task_id"])
        if task_id in ready_by_task:
            merged.append(ready_by_task[task_id])
        elif task_id in repaired_by_task:
            merged.append(repaired_by_task[task_id])
    write_jsonl(output_path, merged)
    statuses = Counter(row.get("status", "unknown") for row in results)
    summary = {
        "input_count": len(units),
        "pass_through": pass_through_count,
        "repair_targets": len(targets),
        "env_repaired": statuses.get("env_repaired", 0),
        "env_repair_failed": statuses.get("env_repair_failed", 0),
        "env_ready": len(merged),
        "status_counts": dict(statuses),
    }
    write_stage_report(
        ctx,
        stage,
        started,
        {"instruction_ref_units": {"path": str(input_path.relative_to(ctx.run_dir)), "hash": file_hash(input_path)}},
        {"env_ready_units": {"path": str(output_path.relative_to(ctx.run_dir)), "records": len(merged), "hash": file_hash(output_path)}},
        summary,
        cfg,
    )
