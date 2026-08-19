from __future__ import annotations

import argparse
from typing import Any

from common.context import RunContext, utc_now
from common.hashing import file_hash
from common.io import read_jsonl, write_json, write_jsonl, write_text
from common.model_pool import ModelClient

from facet_terminal.pipeline import ArtifactWriter, base_image, candidate_dir, record_event, stage_cfg, stage_log_dir, stage_report_dir, task_root, worker_count, write_stage_report
from facet_terminal.prompts import PROMPT_VERSION, TEST_USER_PROMPT, render_prompt
from facet_terminal.scheduler import run_batched
from facet_terminal.stages.tests.env_context import capture_environment_state, read_generated_dockerfile
from facet_terminal.stages.tests.test_runner_templates import CANARY, build_test_sh, fallback_test_state


STAGE = "tests"


def _profile_for_unit(profiles: list[str], key: str) -> str | None:
    if not profiles:
        return None
    from common.hashing import short_hash

    return profiles[int(short_hash(key, 8), 16) % len(profiles)]


def normalize_packages(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    packages: list[str] = []
    for item in value:
        package = str(item).strip()
        if not package:
            continue
        if "==" in package:
            package = package.split("==", 1)[0].strip()
            if not package:
                continue
        if any(token in package for token in ("\n", "\r", ";", "&&", "|", "`", "$(")):
            continue
        packages.append(package)
    return packages[:12]


def normalize_test_state(source: str, root: str) -> str:
    text = str(source or "").replace("\r\n", "\n").strip()
    if not text:
        text = fallback_test_state(root).strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("python"):
            text = text[len("python") :].strip()
    if not text.startswith(CANARY):
        lines = text.splitlines()
        if lines and lines[0].startswith("# HARBOR_CANARY:"):
            lines[0] = CANARY
            text = "\n".join(lines)
        else:
            text = CANARY + "\n" + text
    compile(text, "test_state.py", "exec")
    return text.rstrip() + "\n"


def template_test_payload(root: str) -> dict[str, Any]:
    return {"packages": [], "test_state_py": fallback_test_state(root)}


def read_generated_solution(task: Any) -> dict[str, Any]:
    path = task / "solution" / "solve.sh"
    if not path.exists():
        return {"path": "solution/solve.sh", "exists": False, "content": ""}
    return {
        "path": "solution/solve.sh",
        "exists": True,
        "content": path.read_text(encoding="utf-8", errors="replace"),
    }


def test_context(ctx: RunContext, cfg: dict[str, Any], unit: dict[str, Any]) -> dict[str, Any]:
    env_state = capture_environment_state(ctx, cfg, unit)
    task = candidate_dir(ctx, str(unit["task_id"]))
    return {
        "instruction_md": env_state.get("instruction_md", ""),
        "real_env_file_summary": env_state.get("real_env_file_summary", {}),
        "selected_fixture_summaries": env_state.get("selected_fixture_summaries", []),
        "environment_metadata": env_state.get("environment_metadata", {}),
        "generated_dockerfile": read_generated_dockerfile(task),
        "generated_solution": read_generated_solution(task),
        "constraints": {
            "task_root": task_root(cfg),
            "base_image": base_image(ctx, cfg),
            "prompt_version": PROMPT_VERSION,
            "stage": STAGE,
            "solution_available": True,
        },
    }


def tests_payload_from_model(ctx: RunContext, cfg: dict[str, Any], model_client: ModelClient, unit: dict[str, Any], context: dict[str, Any]) -> tuple[dict[str, Any], str | None, str | None]:
    task_id = str(unit["task_id"])
    prompt = render_prompt(TEST_USER_PROMPT, context, task_root=task_root(cfg), base_image=base_image(ctx, cfg))
    log_dir = stage_log_dir(ctx, STAGE, task_id)
    write_json(log_dir / "env_context.json", context)
    write_text(log_dir / "prompt.txt", prompt)
    profile = _profile_for_unit([str(item) for item in cfg.get("model_profiles", [])], str(unit.get("pair_id", task_id)))
    payload, call_id = model_client.chat_json("facet_terminal_tests", str(unit.get("pair_id", task_id)), "", prompt, profile)
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
        "generator": "facet_terminal_solution_aware_tests",
        "mode": str(cfg.get("mode", "llm")),
        "model_profile": profile,
        "model_call_id": call_id,
        "extra_packages": packages,
        "canary": source.startswith(CANARY),
        "solution_snapshot_used": True,
        "environment_context_used": True,
        "instruction_path": "instruction.md",
        "solution_path": "solution/solve.sh",
        "real_env_file_summary_path": "pipeline_artifacts/share/real_env_file_summary.json",
        "selected_fixture_summaries_path": "pipeline_artifacts/share/selected_fixture_summaries.json",
        "environment_metadata": context.get("environment_metadata", {}),
    }
    metadata_rel = writer.write_json(task_id, "pipeline_artifacts/tests/test_metadata.json", metadata)
    return ["tests/test_state.py", "tests/test.sh", "pipeline_artifacts/tests/test_metadata.json"], {
        **metadata,
        "written": [test_state_rel, test_sh_rel, metadata_rel],
    }


def tests_one(ctx: RunContext, cfg: dict[str, Any], model_client: ModelClient | None, unit: dict[str, Any]) -> dict[str, Any]:
    task_id = str(unit["task_id"])
    try:
        context = test_context(ctx, cfg, unit)
        if not str(context.get("instruction_md") or "").strip():
            raise ValueError("instruction_md_missing")
        mode = str(cfg.get("mode", "llm"))
        if mode == "template":
            payload = template_test_payload(task_root(cfg))
            profile = None
            call_id = None
        else:
            if model_client is None:
                raise ValueError("model_client_required_for_llm_tests")
            payload, profile, call_id = tests_payload_from_model(ctx, cfg, model_client, unit, context)
        written, metadata = write_tests_payload(ctx, cfg, unit, payload, context, profile, call_id)
        report = {
            "task_id": task_id,
            "status": "test_ready",
            "mode": mode,
            "model_profile": profile,
            "model_call_id": call_id,
            "canary": True,
            "solution_snapshot_used": True,
            "environment_context_used": True,
            "written": written,
            "extra_packages": metadata.get("extra_packages", []),
        }
        write_json(stage_report_dir(ctx, STAGE) / f"{task_id}.json", report)
        record_event(ctx, task_id, STAGE, "test_ready")
        row = dict(unit)
        row["tests"] = report
        return {"status": "test_ready", "task_id": task_id, "unit": row}
    except Exception as exc:
        report = {"task_id": task_id, "status": "test_failed", "error": repr(exc)}
        write_json(stage_report_dir(ctx, STAGE) / f"{task_id}.json", report)
        record_event(ctx, task_id, STAGE, "test_failed", error=repr(exc))
        return {"status": "test_failed", "task_id": task_id, "unit": unit}


def run(ctx: RunContext, args: argparse.Namespace) -> None:
    started = utc_now()
    cfg = stage_cfg(ctx, STAGE)
    input_path = ctx.path(str(cfg.get("input_jsonl", "artifacts/facet_terminal/solution_units.jsonl")))
    output_path = ctx.path(str(cfg.get("output_jsonl", "artifacts/facet_terminal/test_units.jsonl")))
    if not input_path.exists():
        raise FileNotFoundError(
            f"tests stage input is missing: {input_path}. "
            "Run the solution stage first, or set facet_terminal_tests.input_jsonl to an existing upstream JSONL."
        )
    units = read_jsonl(input_path)
    if args.limit:
        units = units[: args.limit]
    model_client = ModelClient(ctx) if str(cfg.get("mode", "llm")) != "template" else None
    results = run_batched(
        "facet_terminal_tests:solution_aware",
        units,
        worker_count(ctx, STAGE, cfg, args.workers),
        int(cfg.get("batch_size", 8)),
        int(cfg.get("max_inflight_batches", 2)),
        lambda unit: tests_one(ctx, cfg, model_client, unit),
    )
    ready = [row["unit"] for row in results if row.get("status") == "test_ready"]
    write_jsonl(output_path, ready)
    write_stage_report(
        ctx,
        STAGE,
        started,
        {"solution_units": {"path": str(input_path.relative_to(ctx.run_dir)), "hash": file_hash(input_path)}},
        {"test_units": {"path": str(output_path.relative_to(ctx.run_dir)), "records": len(ready), "hash": file_hash(output_path)}},
        {"input_count": len(units), "test_ready": len(ready), "test_failed": len(results) - len(ready), "solution_snapshot_used": True},
        cfg,
    )
