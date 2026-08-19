from __future__ import annotations

import argparse
from typing import Any

from common.context import RunContext, utc_now
from common.hashing import file_hash
from common.io import read_jsonl, write_json, write_jsonl, write_text
from common.model_pool import ModelClient

from facet_terminal.pipeline import ArtifactWriter, base_image, candidate_dir, record_event, stage_cfg, stage_log_dir, stage_report_dir, task_root, worker_count, write_stage_report
from facet_terminal.prompts import PROMPT_VERSION
from facet_terminal.prompts_reverse import REVERSE_INSTRUCTION_USER_PROMPT, render_reverse_prompt
from facet_terminal.scheduler import run_batched
from facet_terminal.stages.instruction.stage import _profile_for_unit, fallback_instruction, instruction_ref_text, real_env_file_summary


STAGE = "reverse_instruction"


def _bundle_from_model(ctx: RunContext, cfg: dict[str, Any], model_client: ModelClient, unit: dict[str, Any]) -> tuple[dict[str, Any], str | None, str | None]:
    task_id = str(unit["task_id"])
    root = task_root(cfg)
    context = {
        "instruction_ref": instruction_ref_text(ctx, unit),
        "real_env_file_summary": real_env_file_summary(unit),
        "constraints": {
            "task_root": root,
            "base_image": base_image(ctx, cfg),
            "prompt_version": PROMPT_VERSION,
            "stage": STAGE,
        },
    }
    prompt = render_reverse_prompt(REVERSE_INSTRUCTION_USER_PROMPT, context, task_root=root, base_image=base_image(ctx, cfg))
    log_dir = stage_log_dir(ctx, STAGE, task_id)
    write_text(log_dir / "prompt.txt", prompt)
    write_json(log_dir / "input_context.json", context)
    profile = _profile_for_unit([str(item) for item in cfg.get("model_profiles", [])], str(unit.get("pair_id", task_id)))
    payload, call_id = model_client.chat_json("facet_terminal_reverse_instruction", str(unit.get("pair_id", task_id)), "", prompt, profile)
    write_json(log_dir / "model_payload.json", payload)
    return payload, profile, call_id


def _normalize_bundle(payload: dict[str, Any], unit: dict[str, Any], root: str) -> dict[str, str]:
    instruction = str(payload.get("instruction_md") or "").strip()
    solution_hint = str(payload.get("solution_hint") or "").strip()
    test_hint = str(payload.get("test_hint") or "").strip()
    if not instruction:
        instruction = fallback_instruction(unit, root).strip()
    if not solution_hint:
        solution_hint = "\n".join(
            [
                "## Construction target",
                f"Create the final artifacts required by the instruction under {root}.",
                "## Source roles and extraction plan",
                "Use the source files explicitly named in the instruction.",
                "## Transformation and ordering plan",
                "Preserve source-derived ordering unless the instruction requires sorting.",
                "## Cross-reference plan",
                "Keep paths and identifiers consistent across generated artifacts.",
                "## Formatting plan",
                "Use the exact formats, paths, headings, keys, and columns stated in the instruction.",
                "## Pitfalls to avoid",
                "Do not invent files, use placeholders, call live services, or modify source fixtures unless required.",
            ]
        )
    if not test_hint:
        test_hint = "\n".join(
            [
                "## Validation scope",
                "Validate the final observable filesystem state required by the instruction.",
                "## Required artifact checks",
                "Check exact output paths, non-empty files, and required formats.",
                "## Source-derived assertions",
                "Derive expected values from local source files named in the instruction.",
                "## Relationship and consistency checks",
                "Check path, count, and cross-artifact consistency.",
                "## Exclusion and robustness checks",
                "Reject placeholders, live-service dependencies, and prohibited content.",
                "## Likely failure modes",
                "Catch missing outputs, incomplete schemas, weak summaries, wrong counts, and invented data.",
            ]
        )
    return {"instruction_md": instruction, "solution_hint": solution_hint, "test_hint": test_hint}


def _write_bundle(ctx: RunContext, task_id: str, bundle: dict[str, str]) -> list[str]:
    writer = ArtifactWriter(ctx, STAGE)
    written = [
        writer.write_text(task_id, "instruction.md", bundle["instruction_md"].rstrip() + "\n"),
        writer.write_json(task_id, "pipeline_artifacts/share/instruction_bundle.json", bundle),
        writer.write_text(task_id, "pipeline_artifacts/share/solution_hint.md", bundle["solution_hint"].rstrip() + "\n"),
        writer.write_text(task_id, "pipeline_artifacts/share/test_hint.md", bundle["test_hint"].rstrip() + "\n"),
    ]
    return written


def instruction_one(ctx: RunContext, cfg: dict[str, Any], model_client: ModelClient | None, unit: dict[str, Any]) -> dict[str, Any]:
    task_id = str(unit["task_id"])
    root = task_root(cfg)
    try:
        mode = str(cfg.get("mode", "llm"))
        if mode == "template":
            payload = {
                "instruction_md": fallback_instruction(unit, root),
                "solution_hint": "",
                "test_hint": "",
            }
            profile = None
            call_id = None
        else:
            if model_client is None:
                raise ValueError("model_client_required_for_llm_reverse_instruction")
            payload, profile, call_id = _bundle_from_model(ctx, cfg, model_client, unit)
        bundle = _normalize_bundle(payload, unit, root)
        written = _write_bundle(ctx, task_id, bundle)
        report = {
            "task_id": task_id,
            "status": "reverse_instruction_ready",
            "mode": mode,
            "model_profile": profile,
            "model_call_id": call_id,
            "written": written,
            "instruction_bundle_path": "pipeline_artifacts/share/instruction_bundle.json",
        }
        write_json(stage_report_dir(ctx, STAGE) / f"{task_id}.json", report)
        record_event(ctx, task_id, STAGE, "reverse_instruction_ready")
        row = dict(unit)
        row["reverse_instruction"] = report
        row["instruction_bundle"] = {
            "instruction_md_path": "instruction.md",
            "bundle_path": "pipeline_artifacts/share/instruction_bundle.json",
            "solution_hint_path": "pipeline_artifacts/share/solution_hint.md",
            "test_hint_path": "pipeline_artifacts/share/test_hint.md",
        }
        return {"status": "reverse_instruction_ready", "task_id": task_id, "unit": row}
    except Exception as exc:
        report = {"task_id": task_id, "status": "reverse_instruction_failed", "error": repr(exc)}
        write_json(stage_report_dir(ctx, STAGE) / f"{task_id}.json", report)
        record_event(ctx, task_id, STAGE, "reverse_instruction_failed", error=repr(exc))
        return {"status": "reverse_instruction_failed", "task_id": task_id, "unit": unit}


def run(ctx: RunContext, args: argparse.Namespace) -> None:
    started = utc_now()
    cfg = stage_cfg(ctx, STAGE)
    input_path = ctx.path(str(cfg.get("input_jsonl", "artifacts/facet_terminal/env_ready_units.jsonl")))
    output_path = ctx.path(str(cfg.get("output_jsonl", "artifacts/facet_terminal/reverse_instruction_units.jsonl")))
    units = read_jsonl(input_path)
    if args.limit:
        units = units[: args.limit]
    model_client = ModelClient(ctx) if str(cfg.get("mode", "llm")) != "template" else None
    results = run_batched(
        "facet_terminal_reverse_instruction:bundle",
        units,
        worker_count(ctx, STAGE, cfg, args.workers),
        int(cfg.get("batch_size", 8)),
        int(cfg.get("max_inflight_batches", 2)),
        lambda unit: instruction_one(ctx, cfg, model_client, unit),
    )
    ready = [row["unit"] for row in results if row.get("status") == "reverse_instruction_ready"]
    write_jsonl(output_path, ready)
    write_stage_report(
        ctx,
        STAGE,
        started,
        {"env_ready_units": {"path": str(input_path.relative_to(ctx.run_dir)), "hash": file_hash(input_path)}},
        {"reverse_instruction_units": {"path": str(output_path.relative_to(ctx.run_dir)), "records": len(ready), "hash": file_hash(output_path)}},
        {"input_count": len(units), "reverse_instruction_ready": len(ready), "reverse_instruction_failed": len(results) - len(ready)},
        cfg,
    )
