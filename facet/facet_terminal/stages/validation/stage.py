from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path
import shutil
import time

from common.context import RunContext, utc_now
from common.hashing import file_hash
from common.io import read_jsonl, write_json, write_jsonl

from facet_terminal.pipeline import candidate_dir, failed_tasks_dir, final_validated_dir, record_event, run_cmd, stage_cfg, stage_report_dir, task_root, tail, worker_count, write_stage_report
from facet_terminal.scheduler import run_batched


def copy_task(src: Path, dest_root: Path) -> None:
    dest = dest_root / src.name
    if dest.exists():
        shutil.rmtree(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(src, dest)


def reward(container_name: str) -> float | None:
    result = run_cmd(["docker", "exec", container_name, "cat", "/logs/verifier/reward.txt"], timeout=20)
    if result.returncode != 0:
        return None
    try:
        return float(result.stdout.strip())
    except ValueError:
        return None


def run_trial(ctx: RunContext, cfg: dict, task_id: str, image_tag: str, mode: str, solve_path: Path | None, task_dir: Path | None = None) -> dict:
    root = task_root(cfg)
    task = task_dir or candidate_dir(ctx, task_id)
    container = f"facet-terminal-{ctx.run_id}-{task_id}-{mode}-{time.time_ns()}".lower().replace("_", "-")
    result = {"mode": mode, "reward": None, "passed": False}
    try:
        start = run_cmd(["docker", "run", "-d", "--name", container, "--network", str(cfg.get("docker_network", "bridge")), image_tag, "sleep", "infinity"], timeout=60)
        result["container_start"] = {"exit_code": start.returncode, "stdout": tail(start.stdout), "stderr": tail(start.stderr)}
        if start.returncode != 0:
            result["failure_type"] = "container_start_failed"
            return result
        run_cmd(["docker", "exec", container, "mkdir", "-p", "/logs/verifier", "/tests"], timeout=20)
        if solve_path is not None:
            run_cmd(["docker", "cp", str(solve_path), f"{container}:{root}/solve.sh"], timeout=60)
            run_cmd(["docker", "exec", container, "chmod", "+x", f"{root}/solve.sh"], timeout=20)
            solve = run_cmd(["docker", "exec", "-w", root, container, "bash", f"{root}/solve.sh"], timeout=int(cfg.get("command_timeout_sec", 300)))
            result["solution"] = {"exit_code": solve.returncode, "stdout": tail(solve.stdout), "stderr": tail(solve.stderr)}
            if solve.returncode != 0:
                result["failure_type"] = "solution_failed"
                return result
        run_cmd(["docker", "cp", str(task / "tests") + "/.", f"{container}:/tests/"], timeout=60)
        run_cmd(["docker", "exec", container, "chmod", "+x", "/tests/test.sh"], timeout=20)
        tests = run_cmd(["docker", "exec", "-w", root, container, "bash", "/tests/test.sh"], timeout=int(cfg.get("command_timeout_sec", 300)))
        result["tests"] = {"exit_code": tests.returncode, "stdout": tail(tests.stdout), "stderr": tail(tests.stderr)}
        result["reward"] = reward(container)
        result["passed"] = result["reward"] == 1
        return result
    except Exception as exc:
        result["failure_type"] = "exception"
        result["error"] = repr(exc)
        return result
    finally:
        if cfg.get("remove_containers", True):
            run_cmd(["docker", "rm", "-f", container], timeout=60)


def classify(report: dict) -> str:
    build = report.get("build", {})
    if build.get("exit_code") != 0:
        return "build_failed"
    if report.get("oracle", {}).get("reward") != 1:
        return "oracle_failed"
    if report.get("nop", {}).get("reward") != 0:
        return "nop_unexpected_pass"
    for partial in report.get("partials", []):
        if partial.get("reward") == 1:
            return "partial_unexpected_pass"
    return "validated"


def validate_task_dir(
    ctx: RunContext,
    cfg: dict,
    unit: dict,
    task: Path,
    *,
    write_report: bool = True,
    copy_outputs: bool = True,
    record_status: bool = True,
    image_suffix: str = "",
) -> dict:
    task_id = str(unit["task_id"])
    suffix = f"-{image_suffix}" if image_suffix else ""
    image_tag = f"facet-terminal-{ctx.run_id}-{task_id}{suffix}".lower().replace("_", "-")
    report = {"task_id": task_id, "status": "unknown", "image_tag": image_tag}
    try:
        build = run_cmd(["docker", "build", "--network", str(cfg.get("build_network", "default")), "-t", image_tag, "."], cwd=task / "environment", timeout=int(cfg.get("build_timeout_sec", 900)))
        report["build"] = {"exit_code": build.returncode, "stdout": tail(build.stdout), "stderr": tail(build.stderr)}
        if build.returncode == 0:
            report["oracle"] = run_trial(ctx, cfg, task_id, image_tag, "oracle", task / "solution" / "solve.sh", task)
            report["nop"] = run_trial(ctx, cfg, task_id, image_tag, "nop", None, task)
            partials = []
            for path in sorted((task / "solution").glob("partial_solve_*.sh"))[: int(cfg.get("max_partial_trials", 3))]:
                partials.append(run_trial(ctx, cfg, task_id, image_tag, path.stem, path, task))
            report["partials"] = partials
        failure_type = classify(report)
        report["failure_type"] = failure_type
        report["status"] = "validated" if failure_type == "validated" else "failed"
        if write_report:
            write_json(stage_report_dir(ctx, "validation") / f"{task_id}.json", report)
        if copy_outputs:
            copy_task(task, final_validated_dir(ctx) if report["status"] == "validated" else failed_tasks_dir(ctx))
        if record_status:
            record_event(ctx, task_id, "validation", report["status"], failure_type=failure_type)
        row = dict(unit)
        row["validation"] = report
        return {"status": report["status"], "task_id": task_id, "failure_type": failure_type, "unit": row}
    except Exception as exc:
        report.update({"status": "failed", "failure_type": "unknown_validation_error", "error": repr(exc)})
        if write_report:
            write_json(stage_report_dir(ctx, "validation") / f"{task_id}.json", report)
        if copy_outputs and task.exists():
            copy_task(task, failed_tasks_dir(ctx))
        if record_status:
            record_event(ctx, task_id, "validation", "failed", failure_type="unknown_validation_error", error=repr(exc))
        return {"status": "failed", "task_id": task_id, "failure_type": "unknown_validation_error", "unit": unit}
    finally:
        if cfg.get("remove_images", True):
            run_cmd(["docker", "rmi", "-f", image_tag], timeout=90)


def validate_one(ctx: RunContext, cfg: dict, unit: dict) -> dict:
    return validate_task_dir(ctx, cfg, unit, candidate_dir(ctx, str(unit["task_id"])))


def run(ctx: RunContext, args: argparse.Namespace) -> None:
    stage = "validation"
    started = utc_now()
    cfg = stage_cfg(ctx, stage)
    input_path = ctx.path(str(cfg.get("input_jsonl", "artifacts/facet_terminal/test_units.jsonl")))
    output_path = ctx.path(str(cfg.get("output_jsonl", "artifacts/facet_terminal/validation_units.jsonl")))
    units = read_jsonl(input_path)
    if args.limit:
        units = units[: args.limit]
    results = run_batched("facet_terminal_validation:docker", units, worker_count(ctx, stage, cfg, args.workers), int(cfg.get("batch_size", 4)), int(cfg.get("max_inflight_batches", 2)), lambda unit: validate_one(ctx, cfg, unit))
    rows = [row["unit"] for row in results]
    write_jsonl(output_path, rows)
    statuses = Counter(row.get("status", "unknown") for row in results)
    failures = Counter(row.get("failure_type", "unknown") for row in results)
    summary = {"input_count": len(units), "validated_total": statuses.get("validated", 0), "failed_total": statuses.get("failed", 0), "status_counts": dict(statuses), "failure_type_counts": dict(failures)}
    write_stage_report(ctx, stage, started, {"test_units": {"path": str(input_path.relative_to(ctx.run_dir)), "hash": file_hash(input_path)}}, {"validation_units": {"path": str(output_path.relative_to(ctx.run_dir)), "records": len(rows), "hash": file_hash(output_path)}}, summary, cfg)
