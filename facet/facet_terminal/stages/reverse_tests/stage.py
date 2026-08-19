from __future__ import annotations

import argparse
from typing import Any

from common.context import RunContext, utc_now
from common.hashing import file_hash
from common.io import read_jsonl, write_json, write_jsonl, write_text
from common.model_pool import ModelClient

from facet_terminal.pipeline import ArtifactWriter, base_image, candidate_dir, record_event, stage_cfg, stage_log_dir, stage_report_dir, task_root, worker_count, write_stage_report
from facet_terminal.prompts import PROMPT_VERSION
from facet_terminal.prompts_reverse import REVERSE_TEST_USER_PROMPT, render_reverse_prompt
from facet_terminal.scheduler import run_batched
from facet_terminal.stages.solution.stage import _profile_for_unit
from facet_terminal.stages.tests.env_context import load_or_build_selected_fixture_summaries, load_real_env_file_summary, read_generated_dockerfile, read_instruction_md
from facet_terminal.stages.tests.stage import normalize_packages, normalize_test_state
from facet_terminal.stages.tests.test_runner_templates import build_test_sh


STAGE = "reverse_tests"


def read_test_hint(task: Any) -> str:
    path = task / "pipeline_artifacts" / "share" / "test_hint.md"
    return path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""


def test_context(ctx: RunContext, cfg: dict[str, Any], unit: dict[str, Any]) -> dict[str, Any]:
    task = candidate_dir(ctx, str(unit["task_id"]))
    instruction_md = read_instruction_md(task, unit)
    real_summary = load_real_env_file_summary(task)
    return {
        "instruction_md": instruction_md,
        "test_hint": read_test_hint(task),
        "selected_fixture_summaries": load_or_build_selected_fixture_summaries(task, cfg, real_summary, prefix="reverse_tests_"),
        "generated_dockerfile": read_generated_dockerfile(task),
        "constraints": {
            "task_root": task_root(cfg),
            "base_image": base_image(ctx, cfg),
            "prompt_version": PROMPT_VERSION,
            "stage": STAGE,
        },
    }


def tests_payload_from_model(ctx: RunContext, cfg: dict[str, Any], model_client: ModelClient, unit: dict[str, Any], context: dict[str, Any]) -> tuple[dict[str, Any], str | None, str | None]:
    task_id = str(unit["task_id"])
    prompt = render_reverse_prompt(REVERSE_TEST_USER_PROMPT, context, task_root=task_root(cfg), base_image=base_image(ctx, cfg))
    log_dir = stage_log_dir(ctx, STAGE, task_id)
    write_json(log_dir / "input_context.json", context)
    write_text(log_dir / "prompt.txt", prompt)
    profile = _profile_for_unit([str(item) for item in cfg.get("model_profiles", [])], str(unit.get("pair_id", task_id)))
    payload, call_id = model_client.chat_json("facet_terminal_reverse_tests", str(unit.get("pair_id", task_id)), "", prompt, profile)
    write_json(log_dir / "model_payload.json", payload)
    return payload, profile, call_id


def write_tests_payload(ctx: RunContext, cfg: dict[str, Any], unit: dict[str, Any], payload: dict[str, Any], context: dict[str, Any], profile: str | None, call_id: str | None) -> tuple[list[str], dict[str, Any]]:
    task_id = str(unit["task_id"])
    root = task_root(cfg)
    writer = ArtifactWriter(ctx, STAGE)
    packages = normalize_packages(payload.get("packages"))
    source = normalize_test_state(str(payload.get("test_state_py") or ""), root)
    test_state_rel = writer.write_text(task_id, "tests/test_state.py", source)
    test_sh_rel = writer.write_text(task_id, "tests/test.sh", build_test_sh(packages), executable=True)
    metadata = {
        "task_id": task_id,
        "generator": "facet_terminal_reverse_tests",
        "mode": str(cfg.get("mode", "llm")),
        "model_profile": profile,
        "model_call_id": call_id,
        "extra_packages": packages,
        "canary": True,
        "instruction_path": "instruction.md",
        "test_hint_path": "pipeline_artifacts/share/test_hint.md",
        "generation_strategy": "REVERSE",
    }
    metadata_rel = writer.write_json(task_id, "pipeline_artifacts/tests/test_metadata.json", metadata)
    return ["tests/test_state.py", "tests/test.sh", "pipeline_artifacts/tests/test_metadata.json"], {**metadata, "written": [test_state_rel, test_sh_rel, metadata_rel]}


def tests_one(ctx: RunContext, cfg: dict[str, Any], model_client: ModelClient | None, unit: dict[str, Any]) -> dict[str, Any]:
    task_id = str(unit["task_id"])
    try:
        context = test_context(ctx, cfg, unit)
        if not str(context.get("instruction_md") or "").strip():
            raise ValueError("instruction_md_missing")
        if not str(context.get("test_hint") or "").strip():
            raise ValueError("test_hint_missing")
        mode = str(cfg.get("mode", "llm"))
        if mode == "template":
            from facet_terminal.stages.tests.stage import template_test_payload

            payload = template_test_payload(task_root(cfg))
            profile = None
            call_id = None
        else:
            if model_client is None:
                raise ValueError("model_client_required_for_llm_reverse_tests")
            payload, profile, call_id = tests_payload_from_model(ctx, cfg, model_client, unit, context)
        written, metadata = write_tests_payload(ctx, cfg, unit, payload, context, profile, call_id)
        report = {
            "task_id": task_id,
            "status": "reverse_test_ready",
            "mode": mode,
            "model_profile": profile,
            "model_call_id": call_id,
            "canary": True,
            "generation_strategy": "REVERSE",
            "written": written,
            "extra_packages": metadata.get("extra_packages", []),
        }
        write_json(stage_report_dir(ctx, STAGE) / f"{task_id}.json", report)
        record_event(ctx, task_id, STAGE, "reverse_test_ready")
        row = dict(unit)
        row["reverse_tests"] = report
        return {"status": "reverse_test_ready", "task_id": task_id, "unit": row}
    except Exception as exc:
        report = {"task_id": task_id, "status": "reverse_test_failed", "error": repr(exc)}
        write_json(stage_report_dir(ctx, STAGE) / f"{task_id}.json", report)
        record_event(ctx, task_id, STAGE, "reverse_test_failed", error=repr(exc))
        return {"status": "reverse_test_failed", "task_id": task_id, "unit": unit}


def run(ctx: RunContext, args: argparse.Namespace) -> None:
    started = utc_now()
    cfg = stage_cfg(ctx, STAGE)
    input_path = ctx.path(str(cfg.get("input_jsonl", "artifacts/facet_terminal/reverse_instruction_units.jsonl")))
    output_path = ctx.path(str(cfg.get("output_jsonl", "artifacts/facet_terminal/reverse_test_units.jsonl")))
    units = read_jsonl(input_path)
    if args.limit:
        units = units[: args.limit]
    model_client = ModelClient(ctx) if str(cfg.get("mode", "llm")) != "template" else None
    results = run_batched(
        "facet_terminal_reverse_tests:reverse",
        units,
        worker_count(ctx, STAGE, cfg, args.workers),
        int(cfg.get("batch_size", 8)),
        int(cfg.get("max_inflight_batches", 2)),
        lambda unit: tests_one(ctx, cfg, model_client, unit),
    )
    ready = [row["unit"] for row in results if row.get("status") == "reverse_test_ready"]
    write_jsonl(output_path, ready)
    write_stage_report(
        ctx,
        STAGE,
        started,
        {"reverse_instruction_units": {"path": str(input_path.relative_to(ctx.run_dir)), "hash": file_hash(input_path)}},
        {"reverse_test_units": {"path": str(output_path.relative_to(ctx.run_dir)), "records": len(ready), "hash": file_hash(output_path)}},
        {"input_count": len(units), "reverse_test_ready": len(ready), "reverse_test_failed": len(results) - len(ready), "generation_strategy": "REVERSE"},
        cfg,
    )
