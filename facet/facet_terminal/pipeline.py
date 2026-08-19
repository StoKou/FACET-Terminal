#!/usr/bin/env python3
"""FACET-Terminal environment-grounded terminal task generation pipeline.

This file is the single CLI/core entrypoint. Stage-specific business
logic lives under ``stages/<stage>/stage.py``; shared project infrastructure
comes from the existing ``common/`` package.

Stage DAG:

    convert_input
      -> selection
      -> planning
      -> skeleton
      -> instruction_ref
      -> env_build
      -> env_repair
      -> selected generation strategy
      -> validation
      -> repair
      -> report

The default FORWARD strategy runs ``instruction -> solution -> tests``. The
``REVERSE`` and ``JOINT`` strategies are experimental
references selected explicitly with ``--strategy``.

Stage responsibilities and default artifacts:

    convert_input
        Reads skill-pair JSONL and writes
        ``artifacts/facet_terminal/input_units.jsonl``.

    selection
        Applies quantity/difficulty/dedupe controls and writes
        ``artifacts/facet_terminal/selected_units.jsonl``.

    planning
        Uses shared prompts to reconstruct a single reference solution workflow
        from each skill pair. The per-task output is
        ``pipeline_artifacts/planning/planning_reference.json`` and the batch index is
        ``artifacts/facet_terminal/planned_units.jsonl``.

    skeleton
        Writes initial Harbor task skeleton files: ``task.toml`` and
        ``manifest.json`` under
        ``artifacts/facet_terminal/tasks/candidates/<task_id>/``.

    instruction_ref
        Generates an internal instruction reference from the planning
        reference workflow. It writes ``pipeline_artifacts/instruction_ref.md``
        for env generation context; it is not the final user-facing task.

    env_build
        Generates environment-only artifacts: ``environment/Dockerfile`` and
        ``environment/task_file/**``. It may optionally build/smoke-test the
        environment when configured, and writes ``env_build_reports``.

    env_repair
        Re-runs environment build only for failed env_build tasks and emits a
        merged ready-unit index for downstream instruction generation.

    instruction
        Generates the final user-facing ``instruction.md`` after environment
        files and ``pipeline_artifacts/share/real_env_file_summary.json`` are known.

    solution
        Generates ``solution/solve.sh`` and ``solution/partial_solve_*.sh``.
        It does not modify environment or tests.

    tests
        Generates state-based ``tests/test_state.py`` and Harbor-compatible
        ``tests/test.sh`` from ``instruction.md``, runtime
        ``real_env_file_summary``, and the generated reference solution.

    validation
        Runs fresh Docker build plus oracle/nop/partial trials. Validated
        tasks are copied to ``final/facet_terminal_tasks/validated``; failed tasks
        are copied to ``artifacts/facet_terminal/tasks/failed``.

    repair
        Applies bounded, targeted repair to failed validation cases and
        revalidates each modified candidate.

    report
        Aggregates stage counts and failure taxonomy into
        ``reports/facet_terminal_summary.json`` and ``reports/facet_terminal_summary.md``.

Common commands:

    # List stages
    uv run python facet_terminal/pipeline.py \
      --config configs/FORWARD.yaml --list-stages

    # Run one stage, clearing that stage and all downstream artifacts first
    uv run python facet_terminal/pipeline.py \
      --config configs/FORWARD.yaml --strategy FORWARD --stage planning --clear

    # Resume one stage from checkpoint where supported
    uv run python facet_terminal/pipeline.py \
      --config configs/FORWARD.yaml --strategy FORWARD --stage planning --resume

    # Clear from a stage without changing which stages are executed
    uv run python facet_terminal/pipeline.py \
      --config configs/FORWARD.yaml --strategy FORWARD \
      --stage planning --clear-from planning

    # Run the full pipeline
    uv run python facet_terminal/pipeline.py \
      --config configs/FORWARD.yaml --strategy FORWARD \
      --stage all --clear-from convert_input

    # Re-run from validation only after editing generated artifacts
    uv run python facet_terminal/pipeline.py \
      --config configs/FORWARD.yaml --strategy FORWARD \
      --stage all --from-stage validation --clear-from validation
"""
from __future__ import annotations

import argparse
import importlib
import os
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if __name__ == "__main__":
    sys.modules.setdefault("facet_terminal.pipeline", sys.modules[__name__])

from common.context import RunContext, utc_now  # noqa: E402
from common.hashing import canonical_json, file_hash, sha256_text, short_hash  # noqa: E402
from common.io import append_jsonl, read_json, read_jsonl, write_json, write_jsonl, write_text  # noqa: E402


PIPELINE_NAME = "facet_terminal"
DEFAULT_TASK_ROOT = "/task_file"
DEFAULT_BASE_IMAGE = "ubuntu:22.04"
STAGES = [
    "convert_input",
    "selection",
    "planning",
    "skeleton",
    "instruction_ref",
    "env_build",
    "env_repair",
    "instruction",
    "solution",
    "tests",
    "reverse_instruction",
    "reverse_tests",
    "reverse_solution",
    "joint",
    "validation",
    "repair",
    "report",
]
STAGE_MODULES = {stage: f"facet_terminal.stages.{stage}.stage" for stage in STAGES}

CLEAR_CHAINS = [
    [
        "convert_input",
        "selection",
        "planning",
        "skeleton",
        "instruction_ref",
        "env_build",
        "env_repair",
        "instruction",
        "solution",
        "tests",
        "validation",
        "repair",
        "report",
    ],
    ["reverse_instruction", "reverse_tests", "reverse_solution", "validation", "repair", "report"],
    ["joint", "validation", "repair", "report"],
]

CLEAR_PATHS = {
    "convert_input": ["artifacts/facet_terminal/input_units.jsonl", "reports/facet_terminal_convert_input.json"],
    "selection": [
        "artifacts/facet_terminal/selected_units.jsonl",
        "artifacts/facet_terminal/rejected_units.jsonl",
        "reports/facet_terminal_selection.json",
    ],
    "planning": [
        "artifacts/facet_terminal/planned_units.jsonl",
        "artifacts/facet_terminal/skill_context_units.jsonl",
        "reports/facet_terminal_planning.json",
        "reports/facet_terminal_skill_context.json",
        "checkpoints/facet_terminal_planning",
        "checkpoints/facet_terminal_skill_context",
        "logs/facet_terminal_planning",
    ],
    "skeleton": [
        "artifacts/facet_terminal/skeleton_units.jsonl",
        "reports/facet_terminal_skeleton.json",
    ],
    "instruction_ref": [
        "artifacts/facet_terminal/instruction_ref_units.jsonl",
        "artifacts/facet_terminal/instruction_ref_reports",
        "reports/facet_terminal_instruction_ref.json",
        "logs/facet_terminal_instruction_ref",
    ],
    "env_build": [
        "artifacts/facet_terminal/env_build_units.jsonl",
        "artifacts/facet_terminal/env_build_reports",
        "reports/facet_terminal_env_build.json",
        "logs/facet_terminal_env_build",
    ],
    "env_repair": [
        "artifacts/facet_terminal/env_ready_units.jsonl",
        "artifacts/facet_terminal/env_repair_reports",
        "reports/facet_terminal_env_repair.json",
        "logs/facet_terminal_env_repair",
    ],
    "instruction": [
        "artifacts/facet_terminal/instruction_units.jsonl",
        "artifacts/facet_terminal/instruction_reports",
        "reports/facet_terminal_instruction.json",
        "logs/facet_terminal_instruction",
    ],
    "tests": [
        "artifacts/facet_terminal/test_units.jsonl",
        "artifacts/facet_terminal/tests_reports",
        "reports/facet_terminal_tests.json",
        "logs/facet_terminal_tests",
    ],
    "solution": [
        "artifacts/facet_terminal/solution_units.jsonl",
        "artifacts/facet_terminal/solution_reports",
        "reports/facet_terminal_solution.json",
        "logs/facet_terminal_solution",
    ],
    "reverse_instruction": [
        "artifacts/facet_terminal/reverse_instruction_units.jsonl",
        "artifacts/facet_terminal/reverse_instruction_reports",
        "reports/facet_terminal_reverse_instruction.json",
        "logs/facet_terminal_reverse_instruction",
    ],
    "reverse_solution": [
        "artifacts/facet_terminal/reverse_solution_units.jsonl",
        "artifacts/facet_terminal/reverse_solution_reports",
        "reports/facet_terminal_reverse_solution.json",
        "logs/facet_terminal_reverse_solution",
    ],
    "reverse_tests": [
        "artifacts/facet_terminal/reverse_test_units.jsonl",
        "artifacts/facet_terminal/reverse_tests_reports",
        "reports/facet_terminal_reverse_tests.json",
        "logs/facet_terminal_reverse_tests",
    ],
    "joint": [
        "artifacts/facet_terminal/joint_units.jsonl",
        "artifacts/facet_terminal/joint_reports",
        "reports/facet_terminal_joint.json",
        "logs/facet_terminal_joint",
    ],
    "validation": [
        "artifacts/facet_terminal/validation_units.jsonl",
        "artifacts/facet_terminal/validation_reports",
        "artifacts/facet_terminal/tasks/failed",
        "final/facet_terminal_tasks/validated",
        "reports/facet_terminal_validation.json",
        "logs/facet_terminal_validation",
    ],
    "repair": [
        "artifacts/facet_terminal/repair_units.jsonl",
        "artifacts/facet_terminal/repair_reports",
        "artifacts/facet_terminal/tasks/repaired",
        "reports/facet_terminal_repair.json",
        "logs/facet_terminal_repair",
    ],
    "report": ["reports/facet_terminal_summary.json", "reports/facet_terminal_summary.md"],
}

STAGE_TASK_ARTIFACTS = {
    "planning": ["pipeline_artifacts/planning", "pipeline_artifacts/planning_reference.json", "pipeline_artifacts/io_spec.json", "pipeline_artifacts/skill_context.json", "pipeline_artifacts/input_unit.json"],
    "skeleton": ["task.toml", "manifest.json"],
    "instruction_ref": ["pipeline_artifacts/instruction_ref.md"],
    "instruction": ["instruction.md"],
    "env_build": ["environment", "pipeline_artifacts/environment", "pipeline_artifacts/share/real_env_file_summary.json", "pipeline_artifacts/share/env_build.json"],
    "tests": ["tests", "pipeline_artifacts/tests"],
    "solution": ["solution"],
    "reverse_instruction": ["instruction.md", "pipeline_artifacts/share/instruction_bundle.json", "pipeline_artifacts/share/solution_hint.md", "pipeline_artifacts/share/test_hint.md"],
    "reverse_solution": ["solution"],
    "reverse_tests": ["tests", "pipeline_artifacts/tests"],
    "joint": ["instruction.md", "tests", "solution", "pipeline_artifacts/tests", "pipeline_artifacts/share/joint_payload.json"],
}

BINARY_FIXTURE_SUFFIXES = {
    ".db",
    ".sqlite",
    ".sqlite3",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".tar",
    ".gz",
    ".tgz",
    ".zip",
    ".bin",
    ".img",
    ".pdf",
    ".docx",
    ".pptx",
    ".xlsx",
    ".mp4",
    ".webm",
    ".mov",
    ".mp3",
    ".wav",
}


def worker_count(ctx: RunContext, stage: str, cfg: dict[str, Any], cli_workers: int | None) -> int:
    if cli_workers:
        return max(1, int(cli_workers))
    if cfg.get("workers"):
        return max(1, int(cfg["workers"]))
    execution = ctx.config.get("execution", {}) or {}
    workers = execution.get("workers", {}) or {}
    for key in (f"facet_terminal_{stage}", stage):
        if workers.get(key):
            return max(1, int(workers[key]))
    return max(1, int(execution.get("default_workers", 1)))


def stage_cfg(ctx: RunContext, stage: str) -> dict[str, Any]:
    cfg = dict(ctx.config.get(f"facet_terminal_{stage}", {}) or {})
    cfg.update(dict(ctx.config.get("facet_terminal", {}).get(stage, {}) or {}))
    return cfg


def scheduler_cfg(ctx: RunContext) -> dict[str, Any]:
    return dict(ctx.config.get("facet_terminal_scheduler", {}) or {})


def task_root(cfg: dict[str, Any]) -> str:
    return str(cfg.get("task_root", DEFAULT_TASK_ROOT)).rstrip("/")


def base_image(ctx: RunContext, cfg: dict[str, Any] | None = None) -> str:
    docker_cfg = dict(ctx.config.get("docker", {}) or {})
    return str((cfg or {}).get("base_image") or docker_cfg.get("base_image") or DEFAULT_BASE_IMAGE)


def resolve_path(ctx: RunContext, value: str | os.PathLike[str]) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    candidate = ctx.config_path.parent / path
    if candidate.exists():
        return candidate.resolve()
    return (ctx.config_path.parent.parent / path).resolve()


def safe_rel_path(value: str) -> bool:
    path = Path(value)
    return bool(value) and not path.is_absolute() and ".." not in path.parts


def unit_key(unit: dict[str, Any]) -> str:
    return str(unit.get("task_id") or unit.get("task_name") or unit.get("pair_id") or short_hash(canonical_json(unit), 12))


def task_dir(ctx: RunContext, task_id: str) -> Path:
    return ctx.path(f"artifacts/facet_terminal/tasks/candidates/{task_id}")


def candidate_dir(ctx: RunContext, task_id: str) -> Path:
    return task_dir(ctx, task_id)


def stage_report_dir(ctx: RunContext, stage: str) -> Path:
    return ctx.path(f"artifacts/facet_terminal/{stage}_reports")


def stage_log_dir(ctx: RunContext, stage: str, task_id: str) -> Path:
    return ctx.path(f"logs/facet_terminal_{stage}/{task_id}")


def final_validated_dir(ctx: RunContext) -> Path:
    return ctx.path("final/facet_terminal_tasks/validated")


def failed_tasks_dir(ctx: RunContext) -> Path:
    return ctx.path("artifacts/facet_terminal/tasks/failed")


def repaired_tasks_dir(ctx: RunContext) -> Path:
    return ctx.path("artifacts/facet_terminal/tasks/repaired")


class ArtifactWriter:
    def __init__(self, ctx: RunContext, stage: str) -> None:
        self.ctx = ctx
        self.stage = stage

    def _path(self, task_id: str, rel_path: str) -> Path:
        if not safe_rel_path(rel_path):
            raise ValueError(f"unsafe artifact path: {rel_path}")
        path = candidate_dir(self.ctx, task_id) / rel_path
        root = candidate_dir(self.ctx, task_id).resolve()
        resolved_parent = path.parent.resolve() if path.parent.exists() else path.parent
        if root not in [resolved_parent, *resolved_parent.parents]:
            raise ValueError(f"path escapes task dir: {rel_path}")
        return path

    def write_text(self, task_id: str, rel_path: str, content: str, executable: bool = False) -> str:
        suffixes = {suffix.lower() for suffix in Path(rel_path).suffixes}
        if suffixes & BINARY_FIXTURE_SUFFIXES:
            raise ValueError(f"binary fixture must be generated, not written as text: {rel_path}")
        path = self._path(task_id, rel_path)
        write_text(path, content)
        if executable:
            path.chmod(0o755)
        self._record(task_id, rel_path, path)
        return str(path.relative_to(self.ctx.run_dir))

    def write_json(self, task_id: str, rel_path: str, payload: dict[str, Any]) -> str:
        path = self._path(task_id, rel_path)
        write_json(path, payload)
        self._record(task_id, rel_path, path)
        return str(path.relative_to(self.ctx.run_dir))

    def copytree(self, task_id: str, src: Path, rel_path: str) -> str:
        dest = self._path(task_id, rel_path)
        if dest.exists():
            shutil.rmtree(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(src, dest)
        append_jsonl(
            stage_report_dir(self.ctx, "artifact_writes") / f"{task_id}.jsonl",
            {"created_at": utc_now(), "stage": self.stage, "path": rel_path, "kind": "copytree"},
        )
        return str(dest.relative_to(self.ctx.run_dir))

    def _record(self, task_id: str, rel_path: str, path: Path) -> None:
        append_jsonl(
            stage_report_dir(self.ctx, "artifact_writes") / f"{task_id}.jsonl",
            {"created_at": utc_now(), "stage": self.stage, "path": rel_path, "hash": file_hash(path)},
        )


def record_event(ctx: RunContext, task_id: str, stage: str, status: str, **payload: Any) -> None:
    append_jsonl(
        ctx.path("logs/facet_terminal_events.jsonl"),
        {"created_at": utc_now(), "task_id": task_id, "stage": stage, "status": status, **payload},
    )
    status_path = ctx.path(f"artifacts/facet_terminal/task_status/{task_id}.json")
    current = read_json(status_path) if status_path.exists() else {"task_id": task_id, "history": []}
    current["status"] = status
    current["stage"] = stage
    current["updated_at"] = utc_now()
    current.setdefault("history", []).append({"stage": stage, "status": status, "created_at": utc_now(), **payload})
    write_json(status_path, current)


def write_stage_report(ctx: RunContext, stage: str, started_at: str, inputs: dict[str, Any], outputs: dict[str, Any], summary: dict[str, Any], cfg: dict[str, Any]) -> None:
    report_path = ctx.path(str(cfg.get("report_json", f"reports/facet_terminal_{stage}.json")))
    write_json(report_path, {"stage": stage, **summary})
    ctx.manifest(stage=f"facet_terminal_{stage}", status="success", started_at=started_at, inputs=inputs, outputs=outputs, summary=summary, validator={"status": "ok"}, parameters=cfg)


def run_cmd(cmd: list[str], *, cwd: Path | None = None, timeout: int = 300, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=cwd, env=env, text=True, capture_output=True, timeout=timeout)


def tail(text: str, limit: int = 4000) -> str:
    return text[-limit:] if len(text) > limit else text


STRATEGY_STAGES = {
    "FORWARD": ["instruction", "solution", "tests"],
    "REVERSE": ["reverse_instruction", "reverse_tests", "reverse_solution"],
    "JOINT": ["joint"],
}


def stages_to_run(args: argparse.Namespace) -> list[str]:
    if args.stage != "all":
        return [args.stage]
    stages = [
        "convert_input",
        "selection",
        "planning",
        "skeleton",
        "instruction_ref",
        "env_build",
        "env_repair",
        *STRATEGY_STAGES[args.strategy],
        "validation",
        "repair",
        "report",
    ]
    if args.from_stage:
        if args.from_stage not in stages:
            raise ValueError(f"stage {args.from_stage!r} is not part of strategy {args.strategy!r}")
        return stages[stages.index(args.from_stage) :]
    return stages


def clear_stage(ctx: RunContext, stage: str) -> None:
    for rel in CLEAR_PATHS.get(stage, []):
        path = ctx.path(rel)
        if path.is_dir():
            shutil.rmtree(path)
        elif path.exists():
            path.unlink()
    candidate_root = ctx.path("artifacts/facet_terminal/tasks/candidates")
    if not candidate_root.exists():
        return
    for task_dir_path in candidate_root.iterdir():
        if not task_dir_path.is_dir():
            continue
        for rel in STAGE_TASK_ARTIFACTS.get(stage, []):
            path = task_dir_path / rel
            if path.is_dir():
                shutil.rmtree(path)
            elif path.exists():
                path.unlink()
        prune_empty_dirs(task_dir_path)


def prune_empty_dirs(path: Path) -> None:
    if not path.exists() or not path.is_dir():
        return
    for child in sorted(path.iterdir(), reverse=True):
        if child.is_dir():
            prune_empty_dirs(child)
    try:
        path.rmdir()
    except OSError:
        pass


def clear_from_stage(ctx: RunContext, stage: str) -> None:
    for chain in CLEAR_CHAINS:
        if stage in chain:
            stages = chain[chain.index(stage) :]
            break
    else:
        stages = STAGES[STAGES.index(stage) :]
    for item in stages:
        clear_stage(ctx, item)


def run_pipeline(ctx: RunContext, args: argparse.Namespace, run_stages: list[str]) -> None:
    for stage in run_stages:
        print(f"\n== FACET-Terminal stage: {stage} ==", flush=True)
        importlib.import_module(STAGE_MODULES[stage]).run(ctx, args)


def main() -> None:
    parser = argparse.ArgumentParser(description="FACET-Terminal task generation pipeline.")
    parser.add_argument("--config", required=True)
    parser.add_argument("--run-id")
    parser.add_argument("--stage", choices=["all", *STAGES], default="all")
    parser.add_argument(
        "--strategy",
        choices=sorted(STRATEGY_STAGES),
        default="FORWARD",
        help="Generation strategy. FORWARD is the default FACET-Terminal pipeline; REVERSE and JOINT are experimental references.",
    )
    parser.add_argument("--from-stage", choices=STAGES)
    parser.add_argument("--list-stages", action="store_true")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--workers", type=int)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--clear", action="store_true")
    parser.add_argument("--clear-from", choices=STAGES)
    args = parser.parse_args()
    if args.list_stages:
        for index, stage in enumerate(STAGES, start=1):
            print(f"{index:02d}. {stage}")
        return
    ctx = RunContext.from_config(Path(args.config), args.run_id)
    run_stages = stages_to_run(args)
    if args.clear_from:
        clear_from_stage(ctx, args.clear_from)
    elif args.clear:
        clear_from_stage(ctx, run_stages[0])
    print(f"facet_terminal_run_dir={ctx.run_dir}", flush=True)
    run_pipeline(ctx, args, run_stages)


if __name__ == "__main__":
    main()
