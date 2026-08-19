from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from common.context import RunContext, utc_now
from common.hashing import file_hash
from common.io import read_json, read_jsonl, write_json, write_jsonl, write_text
from common.model_pool import ModelClient

from facet_terminal.pipeline import ArtifactWriter, base_image, candidate_dir, record_event, safe_rel_path, stage_cfg, stage_log_dir, stage_report_dir, task_root, worker_count, write_stage_report
from facet_terminal.prompts import PROMPT_VERSION
from facet_terminal.prompts_reverse import REVERSE_SOLUTION_USER_PROMPT, render_reverse_prompt
from facet_terminal.scheduler import run_batched
from facet_terminal.stages.solution.stage import _profile_for_unit, normalize_script, template_solution_payload
from facet_terminal.stages.tests.env_context import load_or_build_selected_fixture_summaries, load_real_env_file_summary, read_generated_dockerfile, read_instruction_md


STAGE = "reverse_solution"


def read_generated_test_state(task: Path) -> dict[str, Any]:
    path = task / "tests" / "test_state.py"
    if not path.exists():
        return {"path": "tests/test_state.py", "exists": False, "content": ""}
    return {
        "path": "tests/test_state.py",
        "exists": True,
        "content": path.read_text(encoding="utf-8", errors="replace"),
    }


def read_instruction_bundle(task: Path) -> dict[str, str]:
    path = task / "pipeline_artifacts" / "share" / "instruction_bundle.json"
    if path.exists():
        payload = read_json(path)
        if isinstance(payload, dict):
            return {
                "instruction_md": str(payload.get("instruction_md") or ""),
                "solution_hint": str(payload.get("solution_hint") or ""),
            }
    solution_hint = task / "pipeline_artifacts" / "share" / "solution_hint.md"
    return {
        "instruction_md": (task / "instruction.md").read_text(encoding="utf-8", errors="replace") if (task / "instruction.md").exists() else "",
        "solution_hint": solution_hint.read_text(encoding="utf-8", errors="replace") if solution_hint.exists() else "",
    }


def solution_context(ctx: RunContext, cfg: dict[str, Any], unit: dict[str, Any]) -> dict[str, Any]:
    task_id = str(unit["task_id"])
    task = candidate_dir(ctx, task_id)
    bundle = read_instruction_bundle(task)
    instruction_md = bundle.get("instruction_md") or read_instruction_md(task, unit)
    real_summary = load_real_env_file_summary(task)
    return {
        "instruction_md": instruction_md,
        "solution_hint": bundle.get("solution_hint", ""),
        "selected_fixture_summaries": load_or_build_selected_fixture_summaries(task, cfg, real_summary, prefix="reverse_solution_"),
        "generated_dockerfile": read_generated_dockerfile(task),
        "generated_test_state": read_generated_test_state(task),
        "constraints": {
            "task_root": task_root(cfg),
            "base_image": base_image(ctx, cfg),
            "prompt_version": PROMPT_VERSION,
            "stage": STAGE,
        },
    }


def solution_payload_from_model(ctx: RunContext, cfg: dict[str, Any], model_client: ModelClient, unit: dict[str, Any]) -> tuple[dict[str, Any], str | None, str | None]:
    task_id = str(unit["task_id"])
    context = solution_context(ctx, cfg, unit)
    prompt = render_reverse_prompt(REVERSE_SOLUTION_USER_PROMPT, context, task_root=task_root(cfg), base_image=base_image(ctx, cfg))
    log_dir = stage_log_dir(ctx, STAGE, task_id)
    write_json(log_dir / "input_context.json", context)
    write_text(log_dir / "prompt.txt", prompt)
    profile = _profile_for_unit([str(item) for item in cfg.get("model_profiles", [])], str(unit.get("pair_id", task_id)))
    payload, call_id = model_client.chat_json("facet_terminal_reverse_solution", str(unit.get("pair_id", task_id)), "", prompt, profile)
    write_json(log_dir / "model_payload.json", payload)
    return payload, profile, call_id


def write_solution_payload(ctx: RunContext, cfg: dict[str, Any], unit: dict[str, Any], payload: dict[str, Any]) -> list[str]:
    task_id = str(unit["task_id"])
    root = task_root(cfg)
    writer = ArtifactWriter(ctx, STAGE)
    solution = payload.get("solution_sh")
    if not isinstance(solution, str) or not solution.strip():
        raise ValueError("solution_sh_missing")
    writer.write_text(task_id, "solution/solve.sh", normalize_script(solution, root), executable=True)
    written = ["solution/solve.sh"]
    partials = payload.get("partials")
    if not isinstance(partials, list) or not partials:
        partials = []
    for index, partial in enumerate(partials[:3], start=1):
        if not isinstance(partial, dict):
            continue
        name = str(partial.get("name") or f"partial_solve_{index}.sh")
        if not safe_rel_path(name) or "/" in name or not name.endswith(".sh"):
            name = f"partial_solve_{index}.sh"
        writer.write_text(task_id, f"solution/{name}", normalize_script(str(partial.get("content", "")), root), executable=True)
        written.append(f"solution/{name}")
    if len(written) == 1:
        writer.write_text(task_id, "solution/partial_solve_1.sh", f"#!/bin/bash\nset -e\ncd {root}\nmkdir -p output\n", executable=True)
        written.append("solution/partial_solve_1.sh")
    return written


def solution_one(ctx: RunContext, cfg: dict[str, Any], model_client: ModelClient | None, unit: dict[str, Any]) -> dict[str, Any]:
    task_id = str(unit["task_id"])
    try:
        mode = str(cfg.get("mode", "llm"))
        if mode == "template":
            payload = template_solution_payload(unit, task_root(cfg))
            profile = None
            call_id = None
        else:
            if model_client is None:
                raise ValueError("model_client_required_for_llm_reverse_solution")
            context = solution_context(ctx, cfg, unit)
            if not str(context.get("instruction_md") or "").strip():
                raise ValueError("instruction_md_missing")
            if not str(context.get("solution_hint") or "").strip():
                raise ValueError("solution_hint_missing")
            payload, profile, call_id = solution_payload_from_model(ctx, cfg, model_client, unit)
        written = write_solution_payload(ctx, cfg, unit, payload)
        report = {"task_id": task_id, "status": "reverse_solution_ready", "mode": mode, "model_profile": profile, "model_call_id": call_id, "written": written}
        write_json(stage_report_dir(ctx, STAGE) / f"{task_id}.json", report)
        record_event(ctx, task_id, STAGE, "reverse_solution_ready")
        row = dict(unit)
        row["reverse_solution"] = report
        return {"status": "reverse_solution_ready", "task_id": task_id, "unit": row}
    except Exception as exc:
        report = {"task_id": task_id, "status": "reverse_solution_failed", "error": repr(exc)}
        write_json(stage_report_dir(ctx, STAGE) / f"{task_id}.json", report)
        record_event(ctx, task_id, STAGE, "reverse_solution_failed", error=repr(exc))
        return {"status": "reverse_solution_failed", "task_id": task_id, "unit": unit}


def run(ctx: RunContext, args: argparse.Namespace) -> None:
    started = utc_now()
    cfg = stage_cfg(ctx, STAGE)
    input_path = ctx.path(str(cfg.get("input_jsonl", "artifacts/facet_terminal/reverse_test_units.jsonl")))
    output_path = ctx.path(str(cfg.get("output_jsonl", "artifacts/facet_terminal/reverse_solution_units.jsonl")))
    units = read_jsonl(input_path)
    if args.limit:
        units = units[: args.limit]
    model_client = ModelClient(ctx) if str(cfg.get("mode", "llm")) != "template" else None
    results = run_batched(
        "facet_terminal_reverse_solution:write",
        units,
        worker_count(ctx, STAGE, cfg, args.workers),
        int(cfg.get("batch_size", 8)),
        int(cfg.get("max_inflight_batches", 2)),
        lambda unit: solution_one(ctx, cfg, model_client, unit),
    )
    ready = [row["unit"] for row in results if row.get("status") == "reverse_solution_ready"]
    write_jsonl(output_path, ready)
    write_stage_report(
        ctx,
        STAGE,
        started,
        {"reverse_test_units": {"path": str(input_path.relative_to(ctx.run_dir)), "hash": file_hash(input_path)}},
        {"reverse_solution_units": {"path": str(output_path.relative_to(ctx.run_dir)), "records": len(ready), "hash": file_hash(output_path)}},
        {"input_count": len(units), "reverse_solution_ready": len(ready), "reverse_solution_failed": len(results) - len(ready)},
        cfg,
    )
