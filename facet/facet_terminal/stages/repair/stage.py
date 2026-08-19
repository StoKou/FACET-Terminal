from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path
import shutil
from typing import Any

from common.context import RunContext, utc_now
from common.hashing import file_hash
from common.io import read_json, read_jsonl, write_json, write_jsonl, write_text
from common.model_pool import ModelClient

from facet_terminal.pipeline import (
    base_image,
    candidate_dir,
    final_validated_dir,
    record_event,
    repaired_tasks_dir,
    safe_rel_path,
    stage_cfg,
    stage_log_dir,
    stage_report_dir,
    task_root,
    tail,
    worker_count,
    write_stage_report,
)
from facet_terminal.prompts import PROMPT_VERSION, REPAIR_PROMPT, render_prompt
from facet_terminal.scheduler import run_batched
from facet_terminal.stages.instruction.stage import _profile_for_unit
from facet_terminal.stages.solution.stage import normalize_script
from facet_terminal.stages.validation.stage import copy_task, validate_task_dir


STAGE = "repair"

REPAIR_FILE_LIMITS = {
    "instruction.md": 12000,
    "solution/solve.sh": 24000,
    "tests/test_state.py": 30000,
    "tests/test.sh": 10000,
    "environment/Dockerfile": 16000,
    "task.toml": 8000,
    "manifest.json": 8000,
    "pipeline_artifacts/share/real_env_file_summary.json": 16000,
    "pipeline_artifacts/share/selected_fixture_summaries.json": 16000,
    "pipeline_artifacts/share/instruction_bundle.json": 16000,
    "pipeline_artifacts/share/joint_payload.json": 12000,
}

ALLOWED_REPLACE_EXACT = {
    "instruction.md",
    "solution/solve.sh",
    "tests/test_state.py",
    "tests/test.sh",
    "environment/Dockerfile",
    "task.toml",
}

SUPPORTING_ROOTS = (
    "environment/task_file",
    "pipeline_artifacts/share",
)
SUPPORTING_FILE_MAX_COUNT = 48
SUPPORTING_FILE_MAX_BYTES = 5000


def read_text_excerpt(path: Path, limit: int) -> str:
    if not path.exists() or not path.is_file():
        return ""
    text = path.read_text(encoding="utf-8", errors="replace")
    if len(text) <= limit:
        return text
    return text[: limit // 2] + "\n...[truncated]...\n" + text[-limit // 2 :]


def compact_command_record(record: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(record, dict):
        return {}
    return {
        "exit_code": record.get("exit_code"),
        "stdout_tail": tail(str(record.get("stdout") or ""), 8000),
        "stderr_tail": tail(str(record.get("stderr") or ""), 8000),
    }


def compact_trial(trial: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(trial, dict):
        return {}
    return {
        "mode": trial.get("mode"),
        "reward": trial.get("reward"),
        "passed": trial.get("passed"),
        "failure_type": trial.get("failure_type"),
        "error": trial.get("error"),
        "container_start": compact_command_record(trial.get("container_start")),
        "solution": compact_command_record(trial.get("solution")),
        "tests": compact_command_record(trial.get("tests")),
    }


def compact_validation_report(report: dict[str, Any]) -> dict[str, Any]:
    return {
        "task_id": report.get("task_id"),
        "status": report.get("status"),
        "failure_type": report.get("failure_type"),
        "image_tag": report.get("image_tag"),
        "build": compact_command_record(report.get("build")),
        "oracle": compact_trial(report.get("oracle")),
        "nop": compact_trial(report.get("nop")),
        "partials": [compact_trial(item) for item in report.get("partials", []) if isinstance(item, dict)],
        "error": report.get("error"),
    }


def task_file_snapshot(task_dir: Path) -> dict[str, str]:
    snapshot = {rel: read_text_excerpt(task_dir / rel, limit) for rel, limit in REPAIR_FILE_LIMITS.items()}
    partials = sorted((task_dir / "solution").glob("partial_solve_*.sh"))[:3]
    for path in partials:
        rel = str(path.relative_to(task_dir))
        snapshot[rel] = read_text_excerpt(path, 16000)
    return {key: value for key, value in snapshot.items() if value}


def supporting_artifact_snapshot(task_dir: Path) -> dict[str, Any]:
    files: dict[str, str] = {}
    omitted_files: list[str] = []
    for rel_root in SUPPORTING_ROOTS:
        root = task_dir / rel_root
        if not root.exists():
            continue
        for path in sorted(item for item in root.rglob("*") if item.is_file()):
            rel = str(path.relative_to(task_dir))
            if rel.endswith("/.gitkeep") or rel.endswith(".pyc"):
                continue
            if len(files) >= SUPPORTING_FILE_MAX_COUNT:
                omitted_files.append(rel)
                continue
            files[rel] = read_text_excerpt(path, SUPPORTING_FILE_MAX_BYTES)
    return {
        "files": files,
        "omitted_files": omitted_files,
        "limits": {
            "max_files": SUPPORTING_FILE_MAX_COUNT,
            "max_bytes_per_file": SUPPORTING_FILE_MAX_BYTES,
        },
    }


def extract_task_paths(text: str, root: str) -> set[str]:
    import re

    escaped = re.escape(root.rstrip("/"))
    return set(re.findall(rf"{escaped}/[A-Za-z0-9_./@+=:-]+", text or ""))


def detect_static_issues(task_dir: Path, validation: dict[str, Any], root: str) -> dict[str, Any]:
    instruction = read_text_excerpt(task_dir / "instruction.md", 40000)
    solution = read_text_excerpt(task_dir / "solution/solve.sh", 60000)
    tests = read_text_excerpt(task_dir / "tests/test_state.py", 60000)
    test_sh = read_text_excerpt(task_dir / "tests/test.sh", 20000)
    dockerfile = read_text_excerpt(task_dir / "environment/Dockerfile", 30000)

    instruction_paths = extract_task_paths(instruction, root)
    solution_paths = extract_task_paths(solution, root)
    tests_paths = extract_task_paths(tests, root)

    issues: list[str] = []
    recommendations: list[str] = []
    if validation.get("failure_type") == "build_failed":
        issues.append("docker_build_failed")
        recommendations.append("Fix environment/Dockerfile only when build logs show missing public packages or invalid Docker syntax.")
    if validation.get("failure_type") == "oracle_failed":
        issues.append("oracle_solution_failed")
        recommendations.append("Fix solution/solve.sh or align tests with instruction if tests contradict the user-facing contract.")
    if validation.get("failure_type") == "nop_unexpected_pass":
        issues.append("tests_accept_noop")
        recommendations.append("Strengthen tests so required outputs and substantive content are checked.")
    if validation.get("failure_type") == "partial_unexpected_pass":
        issues.append("tests_accept_partial")
        recommendations.append("Strengthen tests or adjust partial scripts so incomplete work is rejected.")
    if "subprocess" in tests or "os.system" in tests:
        issues.append("tests_execute_commands")
        recommendations.append("Tests should inspect final filesystem state without running commands.")
    if "reward.txt" not in test_sh:
        issues.append("test_runner_reward_missing")
        recommendations.append("Ensure tests/test.sh writes /logs/verifier/reward.txt.")
    if "COPY task_file" not in dockerfile and "COPY ./task_file" not in dockerfile:
        issues.append("dockerfile_may_not_copy_task_file")

    return {
        "task_root": root,
        "issues": sorted(set(issues)),
        "path_alignment": {
            "instruction_paths": sorted(instruction_paths),
            "solution_paths": sorted(solution_paths),
            "tests_paths": sorted(tests_paths),
            "tests_paths_missing_from_instruction": sorted(path for path in tests_paths if path not in instruction_paths and "/input/" not in path),
            "solution_paths_not_in_instruction_or_tests": sorted(path for path in solution_paths if path not in instruction_paths and path not in tests_paths),
        },
        "recommendations": list(dict.fromkeys(recommendations)),
    }


def failure_digest(validation: dict[str, Any]) -> dict[str, Any]:
    oracle = validation.get("oracle", {}) if isinstance(validation.get("oracle"), dict) else {}
    solution = oracle.get("solution", {}) if isinstance(oracle.get("solution"), dict) else {}
    tests = oracle.get("tests", {}) if isinstance(oracle.get("tests"), dict) else {}
    tests_stdout = str(tests.get("stdout") or "")
    tests_stderr = str(tests.get("stderr") or "")
    failed_test_ids: list[str] = []
    assertion_messages: list[str] = []
    for line in tests_stdout.splitlines():
        stripped = line.strip()
        if stripped.startswith(("FAILED ", "ERROR ")) and "::" in stripped:
            failed_test_ids.append(stripped.split(" ", 1)[1].split(" - ", 1)[0])
        if stripped.startswith("E "):
            message = stripped[2:].strip()
            if message and message not in assertion_messages:
                assertion_messages.append(message)

    passing_partials = [
        str(item.get("mode"))
        for item in validation.get("partials", [])
        if isinstance(item, dict) and (item.get("passed") or item.get("reward") == 1)
    ]
    build = validation.get("build", {}) if isinstance(validation.get("build"), dict) else {}
    failure_type = str(validation.get("failure_type") or "unknown")
    if build.get("exit_code") not in (None, 0):
        phase = "docker_build"
    elif solution.get("exit_code") not in (None, 0):
        phase = "solution_runtime"
    elif failure_type == "partial_unexpected_pass":
        phase = "partial_validation"
    elif "ERROR collecting" in tests_stdout or "dependency" in tests_stderr.lower() or "no solution found" in tests_stderr.lower():
        phase = "pytest_setup"
    else:
        phase = "pytest_assertion"
    return {
        "phase": phase,
        "failure_type": failure_type,
        "solution_exit_code": solution.get("exit_code"),
        "solution_error_tail": tail(str(solution.get("stderr") or ""), 4000),
        "tests_exit_code": tests.get("exit_code"),
        "failed_test_ids": list(dict.fromkeys(failed_test_ids))[:30],
        "assertion_messages": assertion_messages[:30],
        "tests_stderr_tail": tail(tests_stderr, 4000),
        "passing_partial_ids": list(dict.fromkeys(passing_partials)),
    }


def effective_allowed_patch_targets(validation: dict[str, Any]) -> list[str]:
    targets = sorted(path for path in ALLOWED_REPLACE_EXACT if path != "environment/Dockerfile")
    failure_type = str(validation.get("failure_type") or "")
    if failure_type == "build_failed":
        targets.append("environment/Dockerfile")
    if failure_type == "partial_unexpected_pass":
        targets.append("solution/partial_solve_*.sh")
    return sorted(targets)


def repair_context(
    task_dir: Path,
    unit: dict[str, Any],
    validation_cfg: dict[str, Any],
    previous_rounds: list[dict[str, Any]],
    base_image_value: str,
    max_rounds: int,
) -> dict[str, Any]:
    root = task_root(validation_cfg)
    validation = unit.get("validation", {}) if isinstance(unit.get("validation"), dict) else {}
    return {
        "task_id": str(unit["task_id"]),
        "current_failure_digest": failure_digest(validation),
        "validation_summary": compact_validation_report(validation),
        "diagnosis_static": detect_static_issues(task_dir, validation, root),
        "previous_rounds": previous_rounds,
        "task_files": task_file_snapshot(task_dir),
        "supporting_artifacts": supporting_artifact_snapshot(task_dir),
        "repair_policy": {
            "convergence": {
                "oracle_reward": 1,
                "nop_reward": 0,
                "partial_rewards": 0,
            },
            "effective_allowed_patch_targets": effective_allowed_patch_targets(validation),
            "round": {
                "current": len(previous_rounds) + 1,
                "max": max_rounds,
                "final_round": len(previous_rounds) + 1 >= max_rounds,
            },
        },
        "constraints": {
            "task_root": root,
            "base_image": base_image_value,
            "prompt_version": PROMPT_VERSION,
        },
    }


def allowed_patch_path(rel: str, *, allow_partial_changes: bool, allow_dockerfile_change: bool) -> bool:
    if not safe_rel_path(rel):
        return False
    if rel == "environment/Dockerfile":
        return allow_dockerfile_change
    if rel in ALLOWED_REPLACE_EXACT:
        return True
    if allow_partial_changes and rel.startswith("solution/partial_solve_") and rel.endswith(".sh") and "/" not in rel[len("solution/") :]:
        return True
    return False


def normalize_patch_content(rel: str, content: str, root: str) -> str:
    text = str(content or "").replace("\r\n", "\n").rstrip() + "\n"
    if rel == "solution/solve.sh" or rel.startswith("solution/partial_solve_"):
        return normalize_script(text, root)
    if rel == "tests/test.sh" and not text.startswith("#!"):
        text = "#!/bin/bash\n" + text
    return text


def apply_repair_patch(
    task_dir: Path,
    payload: dict[str, Any],
    root: str,
    *,
    allow_partial_changes: bool,
    allow_dockerfile_change: bool,
) -> list[str]:
    changed: list[str] = []
    for key in ("files_to_replace", "files_to_add"):
        items = payload.get(key)
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            rel = str(item.get("path") or "").strip()
            if not allowed_patch_path(
                rel,
                allow_partial_changes=allow_partial_changes,
                allow_dockerfile_change=allow_dockerfile_change,
            ):
                continue
            path = task_dir / rel
            if key == "files_to_add" and path.exists():
                continue
            content = normalize_patch_content(rel, str(item.get("content") or ""), root)
            write_text(path, content)
            if rel.endswith(".sh"):
                path.chmod(0o755)
            changed.append(rel)

    delete_items = payload.get("files_to_delete")
    if isinstance(delete_items, list):
        for raw_rel in delete_items:
            rel = str(raw_rel or "").strip()
            if not allowed_patch_path(
                rel,
                allow_partial_changes=allow_partial_changes,
                allow_dockerfile_change=allow_dockerfile_change,
            ):
                continue
            path = task_dir / rel
            if path.exists() and path.is_file():
                path.unlink()
                changed.append(rel)
    return sorted(set(changed))


def repair_artifact_dir(ctx: RunContext, task_id: str) -> Path:
    return stage_report_dir(ctx, STAGE) / task_id


def profile_for_repair(ctx: RunContext, cfg: dict[str, Any], task_id: str) -> str | None:
    profiles = [str(item) for item in cfg.get("model_profiles", [])]
    if not profiles:
        solution_cfg = stage_cfg(ctx, "solution")
        profiles = [str(item) for item in solution_cfg.get("model_profiles", [])]
    return _profile_for_unit(profiles, task_id)


def repair_one(ctx: RunContext, cfg: dict[str, Any], validation_cfg: dict[str, Any], model_client: ModelClient | None, unit: dict[str, Any]) -> dict[str, Any]:
    task_id = str(unit["task_id"])
    validation = unit.get("validation", {}) if isinstance(unit.get("validation"), dict) else {}
    if validation.get("status") == "validated":
        return {"status": "skipped_validated", "task_id": task_id, "unit": unit}

    source = candidate_dir(ctx, task_id)
    if not source.exists():
        source = ctx.path(f"artifacts/facet_terminal/tasks/failed/{task_id}")
    target = repaired_tasks_dir(ctx) / task_id
    if target.exists():
        shutil.rmtree(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, target)

    artifacts_dir = repair_artifact_dir(ctx, task_id)
    if artifacts_dir.exists():
        shutil.rmtree(artifacts_dir)
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    log_dir = stage_log_dir(ctx, STAGE, task_id)
    prompt_log_parts: list[str] = []

    result: dict[str, Any] = {
        "task_id": task_id,
        "status": "unrepaired",
        "initial_failure_type": validation.get("failure_type", "unknown"),
        "rounds": [],
        "repaired_task_dir": str(target.relative_to(ctx.run_dir)),
    }
    previous_rounds: list[dict[str, Any]] = []
    root = task_root(validation_cfg)

    if model_client is None:
        result["reason"] = "model_client_required_for_repair"
        write_json(stage_report_dir(ctx, STAGE) / f"{task_id}.json", result)
        return {"status": "unrepaired", "task_id": task_id, "unit": {**unit, "repair": result}}

    max_rounds = max(1, int(cfg.get("max_rounds", 5)))
    for round_index in range(1, max_rounds + 1):
        context = repair_context(target, unit, validation_cfg, previous_rounds, base_image(ctx, validation_cfg), max_rounds)
        write_json(artifacts_dir / f"round_{round_index:02d}_context.json", context)
        repair_prompt = render_prompt(REPAIR_PROMPT, context, task_root=root, base_image=base_image(ctx, validation_cfg))
        write_text(artifacts_dir / f"round_{round_index:02d}_prompt.txt", repair_prompt)
        prompt_log_parts.append(f"===== REPAIR ROUND {round_index} =====\n{repair_prompt}")
        write_text(log_dir / "prompt.txt", "\n\n".join(prompt_log_parts))
        profile = profile_for_repair(ctx, cfg, task_id)
        try:
            payload, call_id = model_client.chat_json("facet_terminal_repair", f"{task_id}:{round_index}", "", repair_prompt, profile)
            write_json(artifacts_dir / f"round_{round_index:02d}_payload.json", payload)
            if payload.get("infeasible"):
                round_result = {
                    "round": round_index,
                    "status": "infeasible",
                    "model_profile": profile,
                    "model_call_id": call_id,
                    "changed_files": [],
                    "summary": payload.get("summary", ""),
                    "failure_analysis": payload.get("failure_analysis", {}),
                }
                result["rounds"].append(round_result)
                result["status"] = "infeasible"
                break
            changed = apply_repair_patch(
                target,
                payload,
                root,
                allow_partial_changes=validation.get("failure_type") == "partial_unexpected_pass",
                allow_dockerfile_change=validation.get("failure_type") == "build_failed",
            )
            round_result = {
                "round": round_index,
                "status": "patched" if changed else "no_change",
                "model_profile": profile,
                "model_call_id": call_id,
                "changed_files": changed,
                "summary": payload.get("summary", ""),
                "failure_analysis": payload.get("failure_analysis", {}),
                "repair_strategy": payload.get("repair_strategy", []),
            }
        except Exception as exc:
            round_result = {"round": round_index, "status": "model_error", "model_profile": profile, "error": repr(exc), "changed_files": []}

        result["rounds"].append(round_result)
        if round_result.get("changed_files"):
            validation_result = validate_task_dir(
                ctx,
                validation_cfg,
                unit,
                target,
                write_report=False,
                copy_outputs=False,
                record_status=False,
                image_suffix=f"repair-r{round_index}",
            )
            repaired_validation = validation_result.get("unit", {}).get("validation", {})
            write_json(artifacts_dir / f"round_{round_index:02d}_validation.json", repaired_validation)
            round_result["validation"] = {
                "status": repaired_validation.get("status"),
                "failure_type": repaired_validation.get("failure_type"),
            }
            if repaired_validation.get("status") == "validated":
                result["status"] = "repaired"
                result["final_validation"] = repaired_validation
                copy_task(target, final_validated_dir(ctx))
                break
            validation = repaired_validation
            unit = {**unit, "validation": repaired_validation}

        previous_rounds.append(
            {
                "round": round_result.get("round"),
                "status": round_result.get("status"),
                "changed_files": round_result.get("changed_files", []),
                "summary": round_result.get("summary", ""),
                "failure_analysis": round_result.get("failure_analysis", {}),
                "repair_strategy": round_result.get("repair_strategy", []),
                "validation": round_result.get("validation"),
                "failure_digest": failure_digest(validation),
                "error": round_result.get("error"),
            }
        )

    write_json(stage_report_dir(ctx, STAGE) / f"{task_id}.json", result)
    record_event(ctx, task_id, STAGE, result["status"], initial_failure_type=result["initial_failure_type"])
    row = dict(unit)
    row["repair"] = result
    return {"status": result["status"], "task_id": task_id, "unit": row}


def run(ctx: RunContext, args: argparse.Namespace) -> None:
    started = utc_now()
    cfg = stage_cfg(ctx, STAGE)
    validation_cfg = stage_cfg(ctx, "validation")
    input_path = ctx.path(str(cfg.get("input_jsonl", "artifacts/facet_terminal/validation_units.jsonl")))
    output_path = ctx.path(str(cfg.get("output_jsonl", "artifacts/facet_terminal/repair_units.jsonl")))
    units = read_jsonl(input_path)
    if args.limit:
        units = units[: args.limit]

    if not bool(cfg.get("enabled", True)):
        write_jsonl(output_path, [])
        write_stage_report(ctx, STAGE, started, {"validation_units": {"path": str(input_path.relative_to(ctx.run_dir)), "hash": file_hash(input_path)}}, {"repair_units": {"path": str(output_path.relative_to(ctx.run_dir)), "records": 0, "hash": file_hash(output_path)}}, {"repair_enabled": False, "repair_count": 0}, cfg)
        return

    targets = [unit for unit in units if unit.get("validation", {}).get("status") != "validated"]
    max_targets = cfg.get("max_targets")
    if max_targets:
        targets = targets[: int(max_targets)]

    model_client = ModelClient(ctx) if str(cfg.get("mode", "llm")) != "template" else None
    results = run_batched(
        "facet_terminal_repair:repair",
        targets,
        worker_count(ctx, STAGE, cfg, args.workers),
        int(cfg.get("batch_size", 4)),
        int(cfg.get("max_inflight_batches", 2)),
        lambda unit: repair_one(ctx, cfg, validation_cfg, model_client, unit),
    )
    rows = [row["unit"] for row in results]
    write_jsonl(output_path, rows)
    statuses = Counter(row.get("status", "unknown") for row in results)
    initial_failures = Counter(str(row.get("unit", {}).get("repair", {}).get("initial_failure_type", "unknown")) for row in results)
    summary = {
        "validation_count": len(units),
        "repair_input_count": len(targets),
        "repair_count": len(rows),
        "status_counts": dict(statuses),
        "initial_failure_type_counts": dict(initial_failures),
        "repaired_total": statuses.get("repaired", 0),
        "unrepaired_total": statuses.get("unrepaired", 0),
        "infeasible_total": statuses.get("infeasible", 0),
    }
    write_stage_report(
        ctx,
        STAGE,
        started,
        {"validation_units": {"path": str(input_path.relative_to(ctx.run_dir)), "hash": file_hash(input_path)}},
        {"repair_units": {"path": str(output_path.relative_to(ctx.run_dir)), "records": len(rows), "hash": file_hash(output_path)}},
        summary,
        cfg,
    )
