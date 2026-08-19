from __future__ import annotations

import argparse

from common.context import RunContext, utc_now
from common.hashing import file_hash
from common.io import read_json, read_jsonl, write_json, write_jsonl, write_text
from common.model_pool import ModelClient

from facet_terminal.pipeline import ArtifactWriter, base_image, candidate_dir, record_event, stage_cfg, stage_log_dir, stage_report_dir, task_root, worker_count, write_stage_report
from facet_terminal.prompts import INSTRUCTION_USER_PROMPT, PROMPT_VERSION, render_prompt
from facet_terminal.scheduler import run_batched


def _profile_for_unit(profiles: list[str], key: str) -> str | None:
    if not profiles:
        return None
    from common.hashing import short_hash

    return profiles[int(short_hash(key, 8), 16) % len(profiles)]


def planning_reference(unit: dict) -> dict:
    plan = unit.get("planning_reference") or unit.get("task_plan", {}).get("planning_reference", {})
    return plan if isinstance(plan, dict) else {}


def fallback_instruction(unit: dict, root: str) -> str:
    plan = planning_reference(unit)
    env_summary = real_env_file_summary(unit)
    target = f"{root}/output/result.json"
    theme = str(plan.get("task_theme") or "Complete the local terminal task").strip()
    visible_files = env_summary.get("task_files") if isinstance(env_summary.get("task_files"), list) else []
    visible = "Use the visible files in the task directory."
    if visible_files:
        names = [str(item.get("absolute_path") or item.get("path")) for item in visible_files[:5] if isinstance(item, dict) and item.get("path")]
        if names:
            visible = "Use the visible task files under " + ", ".join(names) + "."
    return (
        f"{theme}.\n\n"
        f"{visible} Use the visible files provided under `{root}` and write the required final result to `{target}` as valid JSON.\n"
    )


def real_env_file_summary(unit: dict) -> dict:
    if isinstance(unit.get("real_env_file_summary"), dict):
        return unit["real_env_file_summary"]
    if isinstance(unit.get("env_build_manifest"), dict):
        return unit["env_build_manifest"]
    env_report = unit.get("env_build") or unit.get("env") or {}
    if isinstance(env_report, dict) and isinstance(env_report.get("real_env_file_summary"), dict):
        return env_report["real_env_file_summary"]
    if isinstance(env_report, dict) and isinstance(env_report.get("env_build_manifest"), dict):
        return env_report["env_build_manifest"]
    return {}


def instruction_ref_text(ctx: RunContext, unit: dict) -> str:
    task_id = str(unit["task_id"])
    ref_path = candidate_dir(ctx, task_id) / "pipeline_artifacts" / "instruction_ref.md"
    if ref_path.exists():
        return ref_path.read_text(encoding="utf-8")
    ref = unit.get("instruction_ref") or {}
    return str(ref.get("summary") or "")


def instruction_payload_from_model(ctx: RunContext, cfg: dict, model_client: ModelClient, unit: dict) -> tuple[dict, str | None, str | None]:
    task_id = str(unit["task_id"])
    root = task_root(cfg)
    context = {
        "instruction_ref": instruction_ref_text(ctx, unit),
        "real_env_file_summary": real_env_file_summary(unit),
        "constraints": {"task_root": root, "base_image": base_image(ctx, cfg), "prompt_version": PROMPT_VERSION},
    }
    prompt = render_prompt(INSTRUCTION_USER_PROMPT, context, task_root=root, base_image=base_image(ctx, cfg))
    log_dir = stage_log_dir(ctx, "instruction", task_id)
    write_text(log_dir / "prompt.txt", prompt)
    profile = _profile_for_unit([str(item) for item in cfg.get("model_profiles", [])], str(unit.get("pair_id", task_id)))
    payload, call_id = model_client.chat_json("facet_terminal_instruction", str(unit.get("pair_id", task_id)), "", prompt, profile)
    write_json(log_dir / "model_payload.json", payload)
    return payload, profile, call_id


def instruction_one(ctx: RunContext, cfg: dict, model_client: ModelClient | None, unit: dict) -> dict:
    task_id = str(unit["task_id"])
    root = task_root(cfg)
    try:
        mode = str(cfg.get("mode", "llm"))
        if mode == "template":
            payload = {"instruction_md": fallback_instruction(unit, root)}
            profile = None
            call_id = None
        else:
            if model_client is None:
                raise ValueError("model_client_required_for_llm_instruction")
            payload, profile, call_id = instruction_payload_from_model(ctx, cfg, model_client, unit)
        instruction = str(payload.get("instruction_md") or "").strip()
        if not instruction:
            raise ValueError("instruction_md_missing")
        writer = ArtifactWriter(ctx, "instruction")
        writer.write_text(task_id, "instruction.md", instruction.rstrip() + "\n")
        report = {"task_id": task_id, "status": "instruction_ready", "mode": mode, "model_profile": profile, "model_call_id": call_id, "written": ["instruction.md"]}
        write_json(stage_report_dir(ctx, "instruction") / f"{task_id}.json", report)
        record_event(ctx, task_id, "instruction", "instruction_ready")
        row = dict(unit)
        row["instruction"] = report
        return {"status": "instruction_ready", "task_id": task_id, "unit": row}
    except Exception as exc:
        report = {"task_id": task_id, "status": "instruction_failed", "error": repr(exc)}
        write_json(stage_report_dir(ctx, "instruction") / f"{task_id}.json", report)
        record_event(ctx, task_id, "instruction", "instruction_failed", error=repr(exc))
        return {"status": "instruction_failed", "task_id": task_id, "unit": unit}


def run(ctx: RunContext, args: argparse.Namespace) -> None:
    stage = "instruction"
    started = utc_now()
    cfg = stage_cfg(ctx, stage)
    input_path = ctx.path(str(cfg.get("input_jsonl", "artifacts/facet_terminal/env_ready_units.jsonl")))
    output_path = ctx.path(str(cfg.get("output_jsonl", "artifacts/facet_terminal/instruction_units.jsonl")))
    units = read_jsonl(input_path)
    if args.limit:
        units = units[: args.limit]
    model_client = ModelClient(ctx) if str(cfg.get("mode", "llm")) != "template" else None
    results = run_batched(
        "facet_terminal_instruction:write",
        units,
        worker_count(ctx, stage, cfg, args.workers),
        int(cfg.get("batch_size", 8)),
        int(cfg.get("max_inflight_batches", 2)),
        lambda unit: instruction_one(ctx, cfg, model_client, unit),
    )
    ready = [row["unit"] for row in results if row.get("status") == "instruction_ready"]
    write_jsonl(output_path, ready)
    write_stage_report(
        ctx,
        stage,
        started,
        {"env_ready_units": {"path": str(input_path.relative_to(ctx.run_dir)), "hash": file_hash(input_path)}},
        {"instruction_units": {"path": str(output_path.relative_to(ctx.run_dir)), "records": len(ready), "hash": file_hash(output_path)}},
        {"input_count": len(units), "instruction_ready": len(ready), "instruction_failed": len(results) - len(ready)},
        cfg,
    )
