from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import sys

from common.context import RunContext, utc_now
from common.hashing import file_hash
from common.io import read_jsonl, write_json, write_jsonl, write_text
from common.model_pool import ModelClient

from facet_terminal.pipeline import ArtifactWriter, base_image, candidate_dir, record_event, run_cmd, safe_rel_path, stage_cfg, stage_log_dir, stage_report_dir, task_root, tail, worker_count, write_stage_report
from facet_terminal.prompts import ENV_REPAIR_USER_PROMPT, ENV_USER_PROMPT, PROMPT_VERSION, render_prompt
from facet_terminal.scheduler import run_batched


STAGE = "env_build"
TOOL_DIR = Path(__file__).resolve().parent / "tooling" / "scripts"
DOCKERFILE_TEMPLATE_PATH = Path(__file__).resolve().parents[2] / "harbor-template" / "environment" / "Dockerfile"
REAL_ENV_FILE_SUMMARY_PATH = "pipeline_artifacts/share/real_env_file_summary.json"


def _profile_for_unit(profiles: list[str], key: str) -> str | None:
    if not profiles:
        return None
    from common.hashing import short_hash

    return profiles[int(short_hash(key, 8), 16) % len(profiles)]


def template_env_payload(unit: dict, root: str) -> dict:
    scenarios = [str(item) for item in unit.get("scenario_texts", []) if str(item).strip()]
    metadata = {"pair_id": unit.get("pair_id"), "skill_ids": unit.get("skill_ids", []), "scenario_count": len(scenarios)}
    return {
        "dockerfile": render_dockerfile_template(read_dockerfile_template(), "ubuntu:22.04", root),
        "build_context_files": {
            "task_file/input/scenarios.txt": "\n---\n".join(scenarios) + "\n",
            "task_file/input/metadata.json": json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
            "task_file/output/.gitkeep": "",
        },
        "env_checks": [f"test -f {root}/input/scenarios.txt", f"test -f {root}/input/metadata.json", f"test -d {root}/output"],
        "notes": "template fallback environment",
    }


def read_dockerfile_template() -> str:
    return DOCKERFILE_TEMPLATE_PATH.read_text(encoding="utf-8")


def render_dockerfile_template(template: str, image: str, root: str) -> str:
    text = template.replace("__BASE_IMAGE__", image).replace("__TASK_ROOT__", root)
    if re.search(r"(?m)^FROM\s+\S+", text):
        text = re.sub(r"(?m)^FROM\s+\S+", f"FROM {image}", text, count=1)
    else:
        text = f"FROM {image}\n\n{text}"
    if re.search(r"(?m)^WORKDIR\s+\S+", text):
        text = re.sub(r"(?m)^WORKDIR\s+\S+", f"WORKDIR {root}", text, count=1)
    else:
        text = text.rstrip() + f"\n\nWORKDIR {root}\n"
    if not re.search(r"(?m)^COPY\s+task_file/\s+", text):
        text = text.rstrip() + f"\nCOPY task_file/ {root}/\n"
    return text.rstrip() + "\n"


def normalize_env_payload(unit: dict, payload: dict, root: str, image: str | None = None) -> dict:
    normalized = dict(payload)
    context_files = normalized.get("build_context_files")
    if not isinstance(context_files, dict) or not context_files:
        fallback = template_env_payload(unit, root)
        normalized["build_context_files"] = fallback["build_context_files"]
        checks = [
            str(item)
            for item in (normalized.get("env_checks") or [])
            if not re.match(r"^\s*test\s+-[fd]\s+(/task_file|__TASK_ROOT__)/", str(item))
        ]
        for item in fallback["env_checks"]:
            if item not in checks:
                checks.append(item)
        normalized["env_checks"] = checks
    if not isinstance(normalized.get("dockerfile"), str) or not str(normalized.get("dockerfile")).strip():
        normalized["dockerfile"] = render_dockerfile_template(read_dockerfile_template(), image or "ubuntu:22.04", root)
    if not isinstance(normalized.get("env_checks"), list):
        normalized["env_checks"] = []
    add_fixture_manifest(normalized)
    return normalized


def add_fixture_manifest(payload: dict) -> None:
    context_files = payload.get("build_context_files")
    if not isinstance(context_files, dict):
        return
    if "task_file/input/fixture_manifest.json" in context_files or "task_file/inputs/fixture_manifest.json" in context_files:
        return
    manifest_path = "task_file/inputs/fixture_manifest.json" if any(normalize_build_context_path(str(path), "/task_file").startswith("task_file/inputs/") for path in context_files) else "task_file/input/fixture_manifest.json"
    fixtures = []
    for raw_path in sorted(context_files):
        context_rel = normalize_build_context_path(str(raw_path), "/task_file")
        if not context_rel.startswith("task_file/") or context_rel == manifest_path:
            continue
        rel = context_rel[len("task_file/") :]
        is_empty_dir_marker = Path(rel).name == ".gitkeep"
        fixtures.append(
            {
                "path": rel,
                "kind": fixture_kind(rel),
                "role": "empty workspace directory marker" if is_empty_dir_marker else "visible starting fixture",
                "source_strategy": "empty_directory" if is_empty_dir_marker else "synthesized",
                "generation_method": "pipeline_auto_manifest" if context_rel == manifest_path else "inline_build_context",
                "reason": "prepared directory for task outputs" if is_empty_dir_marker else "representative local fixture inferred from instruction_ref",
            }
        )
    context_files[manifest_path] = json.dumps(
        {
            "generated_by": "env_build",
            "fixtures": fixtures,
            "empty_directories": sorted({str(Path(item["path"]).parent) for item in fixtures if "/" in item["path"] and Path(item["path"]).name == ".gitkeep"}),
        },
        ensure_ascii=False,
        indent=2,
    ) + "\n"


def fixture_kind(path: str) -> str:
    suffix = Path(path).suffix.lower().lstrip(".")
    return suffix or "text"


SIMPLE_INLINE_SUFFIXES = {
    ".txt",
    ".log",
    ".csv",
    ".tsv",
    ".json",
    ".jsonl",
    ".md",
    ".markdown",
    ".yaml",
    ".yml",
    ".html",
    ".htm",
    ".xml",
    ".py",
    ".js",
    ".ts",
    ".css",
    ".toml",
    ".ini",
    ".cfg",
    ".conf",
    ".sql",
    ".dot",
    ".svg",
    ".srt",
    ".vtt",
}
SIMPLE_INLINE_NAMES = {
    ".dockerignore",
    ".env",
    ".gitkeep",
    "license",
    "makefile",
    "readme",
}
DEFAULT_MAX_INLINE_FIXTURE_BYTES = 40000


def is_simple_inline_fixture(path: str, content: str, max_bytes: int = DEFAULT_MAX_INLINE_FIXTURE_BYTES) -> bool:
    name = Path(path).name.lower()
    suffix = Path(path).suffix.lower()
    if len(content.encode("utf-8", errors="replace")) > max_bytes:
        return False
    return name in SIMPLE_INLINE_NAMES or suffix in SIMPLE_INLINE_SUFFIXES


def non_inline_fixture_error(path: str, content: str, max_bytes: int = DEFAULT_MAX_INLINE_FIXTURE_BYTES) -> str:
    if len(content.encode("utf-8", errors="replace")) > max_bytes:
        return f"large_inline_fixture_must_be_generated_by_build_script:{path}"
    return f"non_simple_fixture_must_be_generated_by_build_script:{path}"


def generated_runtime_file_record(root: str, task_rel: str, reason: str) -> dict:
    return {
        "path": task_rel.strip("/"),
        "kind": fixture_kind(task_rel),
        "source_strategy": "generated_or_downloaded",
        "generation_method": "build_script_or_dockerfile_run",
        "checked_by": env_check_for_file(root, task_rel),
        "reason": reason,
    }


def ensure_env_check(payload: dict, check: str) -> None:
    checks = payload.get("env_checks")
    if not isinstance(checks, list):
        checks = []
    if check not in checks:
        checks.append(check)
    payload["env_checks"] = checks


def env_check_for_file(root: str, task_rel: str) -> str:
    return f"test -f {shlex.quote(root.rstrip('/') + '/' + task_rel.strip('/'))}"


def normalize_task_rel_path(raw_path: str, root: str) -> str:
    rel = str(raw_path).strip().lstrip("/")
    if rel.startswith("environment/task_file/"):
        rel = rel[len("environment/task_file/") :]
    if rel.startswith(root.rstrip("/").lstrip("/") + "/"):
        rel = rel[len(root.rstrip("/").lstrip("/") + "/") :]
    if rel.startswith(root.rstrip("/") + "/"):
        rel = rel[len(root.rstrip("/") + "/") :]
    return rel.strip("/")


def normalize_build_context_path(raw_path: str, root: str) -> str:
    rel = str(raw_path).strip().replace("\\", "/").lstrip("/")
    if rel.startswith("environment/"):
        rel = rel[len("environment/") :]
    root_rel = root.rstrip("/").lstrip("/")
    if rel.startswith(root_rel + "/"):
        rel = "task_file/" + rel[len(root_rel) + 1 :]
    if rel.startswith(root.rstrip("/") + "/"):
        rel = "task_file/" + rel[len(root.rstrip("/")) + 1 :]
    if rel and not rel.startswith(("task_file/", "build_scripts/")):
        rel = "task_file/" + rel
    return rel.strip("/")


def instruction_ref_text(ctx: RunContext, task_id: str) -> str:
    ref_path = candidate_dir(ctx, task_id) / "pipeline_artifacts" / "instruction_ref.md"
    return ref_path.read_text(encoding="utf-8") if ref_path.exists() else ""


def extracted_final_output_paths(instruction_ref: str, root: str) -> set[str]:
    paths: set[str] = set()
    root_pattern = re.escape(root.rstrip("/"))
    for match in re.finditer(root_pattern + r"/[A-Za-z0-9_./@+=:-]+", instruction_ref):
        rel = normalize_task_rel_path(match.group(0).rstrip(".,);:]'\"`"), root)
        if is_probable_final_output_path(rel):
            paths.add(rel.lower())
    return paths


def is_probable_final_output_path(rel_path: str) -> bool:
    rel = rel_path.strip("/").lower()
    if not rel:
        return False
    path = Path(rel)
    first = path.parts[0] if path.parts else ""
    final_dirs = {"output", "outputs", "result", "results", "final", "submission", "submissions", "deliverables"}
    if first in final_dirs and path.suffix:
        return True
    name = path.name
    input_roots = {"input", "inputs", "fixture", "fixtures", "data", "source", "sources"}
    if first in input_roots:
        return False
    if re.fullmatch(r"final[_-]report\.[a-z0-9]+", name):
        return True
    if re.fullmatch(r"submission[_-].+\.[a-z0-9]+", name):
        return True
    if re.fullmatch(r"consolidated[_-].+\.json", name):
        return True
    return False


def assert_not_final_output(rel_path: str, forbidden_outputs: set[str]) -> None:
    rel = rel_path.strip("/").lower()
    if rel in forbidden_outputs or is_probable_final_output_path(rel):
        raise ValueError(f"final_output_file_not_allowed_in_env:{rel_path}")


def env_payload_from_model(ctx: RunContext, cfg: dict, model_client: ModelClient, unit: dict) -> tuple[dict, str | None, str | None]:
    task_id = str(unit["task_id"])
    root = task_root(cfg)
    instruction_ref_path = candidate_dir(ctx, task_id) / "pipeline_artifacts" / "instruction_ref.md"
    context = {
        "instruction_ref": instruction_ref_path.read_text(encoding="utf-8") if instruction_ref_path.exists() else "",
        "dockerfile_template": render_dockerfile_template(read_dockerfile_template(), base_image(ctx, cfg), root),
        "constraints": {"task_root": root, "base_image": base_image(ctx, cfg), "prompt_version": PROMPT_VERSION},
    }
    if isinstance(unit.get("env_repair_hint"), dict):
        context["env_repair_hint"] = unit["env_repair_hint"]
    prompt = render_prompt(ENV_USER_PROMPT, context, task_root=root, base_image=base_image(ctx, cfg))
    log_dir = stage_log_dir(ctx, STAGE, task_id)
    write_text(log_dir / "prompt.txt", prompt)
    profile = _profile_for_unit([str(item) for item in cfg.get("model_profiles", [])], str(unit.get("pair_id", task_id)))
    payload, call_id = model_client.chat_json("facet_terminal_env_build", str(unit.get("pair_id", task_id)), "", prompt, profile)
    write_json(log_dir / "model_payload.json", payload)
    return payload, profile, call_id


def env_artifact_kind(path: str) -> str:
    if path.endswith("/"):
        return "directory"
    if path == "environment/Dockerfile":
        return "dockerfile"
    if path.startswith("environment/build_scripts/"):
        return "fixture_generator"
    if path.startswith("pipeline_artifacts/"):
        return "metadata"
    return "fixture"


def env_artifact_visible_path(path: str) -> str:
    if path.startswith("environment/task_file/"):
        return path[len("environment/task_file/") :]
    return path


def env_artifact_role(path: str, kind: str) -> str:
    if kind == "dockerfile":
        return "container build definition generated from the fixed base image"
    if kind == "fixture_generator":
        return "deterministic build-time generator for non-text or structured fixtures"
    if kind == "directory":
        return "empty workspace directory prepared for task execution"
    if kind == "metadata":
        return "pipeline metadata describing environment construction inputs"
    return "visible starting fixture for the terminal task"


def env_artifact_source_metadata(path: str, kind: str) -> dict:
    if kind == "dockerfile":
        return {
            "source_strategy": "template_and_model",
            "generation_method": "dockerfile_template_plus_env_build_model",
        }
    if kind == "fixture_generator":
        return {
            "source_strategy": "generated",
            "generation_method": "build_script",
        }
    if kind == "directory":
        return {
            "source_strategy": "empty_directory",
            "generation_method": "gitkeep_marker",
        }
    if kind == "metadata":
        return {
            "source_strategy": "pipeline_metadata",
            "generation_method": "env_build_stage",
        }
    if Path(path).name == ".gitkeep":
        return {
            "source_strategy": "empty_directory",
            "generation_method": "gitkeep_marker",
        }
    return {
        "source_strategy": "synthesized",
        "generation_method": "inline_build_context",
    }


def build_real_env_file_summary(cfg: dict, payload: dict, report: dict, written: list[str]) -> dict:
    build = report.get("build") if isinstance(report.get("build"), dict) else {}
    smoke = report.get("smoke") if isinstance(report.get("smoke"), dict) else {}
    runtime_inventory = report.get("runtime_inventory") if isinstance(report.get("runtime_inventory"), dict) else {}
    task_files = list(runtime_inventory.get("task_files") or [])
    task_directories = list(runtime_inventory.get("task_directories") or [])
    return {
        "task_root": task_root(cfg),
        "summary_type": "real_env_file_summary",
        "description": "Runtime-visible task workspace files collected from the built environment for downstream instruction generation.",
        "collection_method": runtime_inventory.get("collection_method"),
        "task_files": task_files,
        "task_file_paths": list(runtime_inventory.get("task_file_paths") or []),
        "relative_task_file_paths": list(runtime_inventory.get("relative_task_file_paths") or []),
        "task_directories": task_directories,
        "task_directory_paths": list(runtime_inventory.get("task_directory_paths") or []),
        "relative_task_directory_paths": list(runtime_inventory.get("relative_task_directory_paths") or []),
        "counts": {
            "task_files": len(task_files),
            "task_directories": len(task_directories),
        },
        "filtered": runtime_inventory.get("filtered", {}),
        "maturity": report.get("maturity", {}),
        "validation": {
            "lint_checked": bool(report.get("lint_checked")),
            "docker_build": bool(report.get("build_checked")),
            "docker_build_success": bool(build.get("success")) if report.get("build_checked") else None,
            "runtime_inventory_collected": bool(runtime_inventory.get("collected")),
            "smoke_check": bool(report.get("smoke_checked")),
            "smoke_exit_code": smoke.get("exit_code") if report.get("smoke_checked") else None,
            "skipped_env_checks": list(report.get("skipped_env_checks") or []),
        },
    }


def write_env_payload(ctx: RunContext, cfg: dict, unit: dict, payload: dict) -> list[str]:
    task_id = str(unit["task_id"])
    root = task_root(cfg)
    writer = ArtifactWriter(ctx, STAGE)
    written = []
    ref_text = instruction_ref_text(ctx, task_id)
    forbidden_outputs = extracted_final_output_paths(ref_text, root)
    writer.write_json(
        task_id,
        "pipeline_artifacts/environment/env_signals.json",
        {
            "task_id": task_id,
            "base_image": base_image(ctx, cfg),
            "task_root": root,
            "instruction_ref_path": "pipeline_artifacts/instruction_ref.md",
            "forbidden_output_paths": sorted(forbidden_outputs),
        },
    )
    written.append("pipeline_artifacts/environment/env_signals.json")
    context_files = payload.get("build_context_files")
    if not isinstance(context_files, dict) or not context_files:
        raise ValueError("build_context_files_missing")
    has_build_scripts = any(normalize_build_context_path(str(path), root).startswith("build_scripts/") for path in context_files)
    normalized_files: dict[str, str] = {}
    generated_runtime_files: list[dict] = []
    discarded_direct_context_files: list[str] = []
    max_inline_bytes = int(cfg.get("max_inline_fixture_bytes", DEFAULT_MAX_INLINE_FIXTURE_BYTES))
    for raw_path, content in context_files.items():
        rel = normalize_build_context_path(str(raw_path), root)
        if not safe_rel_path(rel):
            raise ValueError(f"unsafe_build_context_path:{raw_path}")
        assert_build_context_path_allowed(rel)
        if not isinstance(content, str):
            content = json.dumps(content, ensure_ascii=False, indent=2) + "\n"
        if rel.startswith("task_file/"):
            task_rel = rel[len("task_file/") :]
            assert_not_final_output(task_rel, forbidden_outputs)
            if not is_simple_inline_fixture(task_rel, content, max_inline_bytes):
                reason = non_inline_fixture_error(str(raw_path), content, max_inline_bytes)
                if not has_build_scripts:
                    raise ValueError(reason)
                discarded_direct_context_files.append(rel)
                generated_runtime_files.append(generated_runtime_file_record(root, task_rel, reason))
                ensure_env_check(payload, env_check_for_file(root, task_rel))
                continue
        normalized_files[rel] = content
    payload["build_context_files"] = dict(normalized_files)
    payload["_generated_runtime_files"] = generated_runtime_files
    payload["_discarded_direct_context_files"] = discarded_direct_context_files
    raw_dockerfile = str(payload.get("dockerfile") or "")
    writer.write_text(task_id, "pipeline_artifacts/environment/raw_dockerfile.latest", raw_dockerfile)
    written.append("pipeline_artifacts/environment/raw_dockerfile.latest")
    dockerfile, stripped_validation_runs = sanitize_dockerfile(raw_dockerfile, base_image(ctx, cfg), root, has_build_scripts)
    if stripped_validation_runs:
        writer.write_json(
            task_id,
            "pipeline_artifacts/environment/stripped_dockerfile_checks.json",
            {"stripped_run_layers": stripped_validation_runs},
        )
        written.append("pipeline_artifacts/environment/stripped_dockerfile_checks.json")
    assert_dockerfile_policy(dockerfile)
    writer.write_text(task_id, "environment/Dockerfile", dockerfile)
    written.append("environment/Dockerfile")
    for rel, content in sorted(normalized_files.items()):
        executable = rel.startswith("build_scripts/")
        writer.write_text(task_id, f"environment/{rel}", sanitize_fixture_sh(content) + "\n" if executable else content, executable=executable)
        written.append(f"environment/{rel}")
    return written


def assert_build_context_path_allowed(rel: str) -> None:
    forbidden_prefixes = ("solution/", "tests/", "hidden/", ".git/", "logs/", "validation/")
    forbidden_parts = {".hidden", "__pycache__"}
    if rel == "Dockerfile" or rel.startswith(forbidden_prefixes) or any(part in forbidden_parts for part in Path(rel).parts):
        raise ValueError(f"forbidden_build_context_path:{rel}")
    if rel.startswith("task_file/") and any(part in {"solution", "tests", "hidden", "validation"} for part in Path(rel).parts):
        raise ValueError(f"forbidden_task_file_path:{rel}")


def sanitize_dockerfile(text: str, image: str, root: str, has_build_scripts: bool) -> tuple[str, list[str]]:
    dockerfile = text.replace("__BASE_IMAGE__", image).replace("__TASK_ROOT__", root).strip()
    if not dockerfile:
        dockerfile = render_dockerfile_template(read_dockerfile_template(), image, root).strip()
    if re.search(r"(?m)^FROM\s+\S+", dockerfile):
        dockerfile = re.sub(r"(?m)^FROM\s+\S+", f"FROM {image}", dockerfile, count=1)
    else:
        dockerfile = f"FROM {image}\n\n{dockerfile}"
    if not re.search(rf"(?m)^WORKDIR\s+{re.escape(root)}\s*$", dockerfile):
        dockerfile = dockerfile.rstrip() + f"\n\nWORKDIR {root}"
    if not re.search(r"(?m)^COPY\s+task_file/\s+", dockerfile):
        dockerfile = dockerfile.rstrip() + f"\nCOPY task_file/ {root}/"
    if has_build_scripts and not re.search(r"(?m)^COPY\s+build_scripts/\s+", dockerfile):
        dockerfile = dockerfile.rstrip() + "\nCOPY build_scripts/ /tmp/facet-build-scripts/"
    dockerfile, stripped = strip_validation_run_layers(dockerfile)
    return dockerfile.rstrip() + "\n", stripped


def strip_validation_run_layers(dockerfile: str) -> tuple[str, list[str]]:
    kept: list[str] = []
    stripped: list[str] = []
    for block in dockerfile_instruction_blocks(dockerfile):
        if is_validation_only_run(block):
            stripped.append(block.strip())
            continue
        kept.append(block.rstrip())
    return "\n".join(item for item in kept if item.strip()) + "\n", stripped


def dockerfile_instruction_blocks(dockerfile: str) -> list[str]:
    blocks: list[str] = []
    current: list[str] = []
    for line in dockerfile.splitlines():
        current.append(line)
        if line.rstrip().endswith("\\"):
            continue
        blocks.append("\n".join(current))
        current = []
    if current:
        blocks.append("\n".join(current))
    return blocks


def dockerfile_instruction(block: str) -> str:
    for line in block.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            return stripped
    return ""


def is_validation_only_run(block: str) -> bool:
    instruction = dockerfile_instruction(block)
    if not instruction.upper().startswith("RUN "):
        return False
    command = re.sub(r"\\\s*\n", " ", instruction[4:]).strip()
    compact = re.sub(r"\s+", " ", command).strip()
    lower = compact.lower()
    if any(marker in lower for marker in ("apt-get ", " apt ", "pip install", "pip3 install", "npm install", "curl ", "wget ")):
        return False
    if any(marker in lower for marker in ("/tmp/facet-build-scripts/", "/task_file/build_scripts/", "build_scripts/")):
        return False
    if re.match(r"^(test\s+|which\s+|command\s+-v\s+)", lower):
        return True
    if re.match(r"^(python3?|python)\s+-c\s+", lower):
        return python_inline_is_validation(lower)
    if re.match(r"^(set\s+-e\s*;?\s*)?(test\s+|which\s+|command\s+-v\s+)", lower):
        return True
    if re.match(r"^(set\s+-e\s*;?\s*)?(python3?|python)\s+-c\s+", lower):
        return python_inline_is_validation(lower)
    return False


def python_inline_is_validation(lower_command: str) -> bool:
    validation_markers = (
        "json.load",
        "csv.dictreader",
        "os.path.isfile",
        "os.path.exists",
        "assert ",
        "missing fixture",
        "all fixtures",
        "print('ok",
        'print("ok',
        "print('all",
        'print("all',
    )
    if not any(marker in lower_command for marker in validation_markers):
        return False
    mutation_markers = (
        "open(",
        ".write(",
        "sqlite3.connect",
        "zipfile.",
        "tarfile.",
        "mkdir",
        "makedirs",
    )
    read_only_open = "open('/task_file/input" in lower_command or 'open("/task_file/input' in lower_command or "open('input/" in lower_command or 'open("input/' in lower_command
    if any(marker in lower_command for marker in mutation_markers) and not read_only_open:
        return False
    return True


def assert_dockerfile_policy(dockerfile: str) -> None:
    forbidden_copy = re.compile(r"(?im)^\s*(COPY|ADD)\s+.*\b(solution|tests|hidden|validation|logs)\b")
    if forbidden_copy.search(dockerfile):
        raise ValueError("dockerfile_forbidden_copy_source")


def sanitize_fixture_sh(script: str) -> str:
    lines = []
    checkout_new = re.compile(r"^(\s*)git\s+checkout\s+-b\s+([A-Za-z0-9._/-]+)\s*$")
    switch_new = re.compile(r"^(\s*)git\s+switch\s+-c\s+([A-Za-z0-9._/-]+)\s*$")
    for line in script.splitlines():
        match = checkout_new.match(line) or switch_new.match(line)
        if match:
            indent, branch = match.groups()
            lines.append(f"{indent}git checkout {branch} 2>/dev/null || git checkout -b {branch}")
            continue
        lines.append(line)
    return "\n".join(lines)


def clear_env_outputs(ctx: RunContext, task_id: str) -> None:
    root_dir = candidate_dir(ctx, task_id)
    shutil.rmtree(root_dir / "environment", ignore_errors=True)
    shutil.rmtree(root_dir / "pipeline_artifacts" / "environment", ignore_errors=True)
    (root_dir / REAL_ENV_FILE_SUMMARY_PATH).unlink(missing_ok=True)
    (root_dir / "pipeline_artifacts" / "share" / "env_build.json").unlink(missing_ok=True)


def smoke_checks(payload: dict) -> tuple[list[str], list[str]]:
    raw_checks = payload.get("env_checks") if isinstance(payload.get("env_checks"), list) else []
    checks: list[str] = []
    skipped: list[str] = []
    secret_name = re.compile(r"\b[A-Z0-9_]*(TOKEN|SECRET|PASSWORD|API_KEY|ACCESS_KEY|CREDENTIAL)[A-Z0-9_]*\b")
    common_commands = {"bash", "cat", "curl", "git", "jq", "node", "npm", "python", "python3", "sh", "test", "which", "yq"}
    for raw_check in raw_checks:
        check = str(raw_check).strip()
        if not check:
            continue
        if "$" in check and secret_name.search(check):
            skipped.append(check)
            continue
        command_match = re.search(r"\b(?:command\s+-v|which)\s+([A-Za-z0-9_.+-]+)", check)
        if command_match and command_match.group(1) not in common_commands:
            skipped.append(check)
            continue
        checks.append(check)
    return checks, skipped


def _json_from_stdout(stdout: str) -> dict:
    try:
        return json.loads(stdout)
    except json.JSONDecodeError:
        return {"raw_stdout": tail(stdout)}


def lint_dockerfile(ctx: RunContext, task_id: str) -> dict:
    dockerfile = candidate_dir(ctx, task_id) / "environment" / "Dockerfile"
    result = run_cmd([sys.executable, str(TOOL_DIR / "lint_dockerfile.py"), str(dockerfile)], timeout=60)
    payload = _json_from_stdout(result.stdout)
    payload["exit_code"] = result.returncode
    payload["stderr"] = tail(result.stderr)
    return payload


def build_dockerfile(ctx: RunContext, cfg: dict, task_id: str, image_tag: str) -> dict:
    environment_dir = candidate_dir(ctx, task_id) / "environment"
    metadata_dir = candidate_dir(ctx, task_id) / "pipeline_artifacts" / "environment" / "build_runtime"
    args = [
        sys.executable,
        str(TOOL_DIR / "build_image.py"),
        "--image-tag",
        image_tag,
        "--dockerfile-dir",
        str(environment_dir),
        "--metadata-dir",
        str(metadata_dir),
        "--network",
        str(cfg.get("build_network", "default")),
        "--build-timeout",
        str(int(cfg.get("build_timeout_sec", 900))),
    ]
    result = run_cmd(args, timeout=int(cfg.get("build_timeout_sec", 900)) + 60, env=dict(os.environ))
    payload = _json_from_stdout(result.stdout)
    payload["exit_code"] = result.returncode
    payload["stderr"] = tail(result.stderr)
    if result.returncode != 0 and payload.get("log_file"):
        parsed = run_cmd([sys.executable, str(TOOL_DIR / "parse_build_log.py"), "--log-file", str(payload["log_file"])], timeout=60)
        payload["parsed_log"] = _json_from_stdout(parsed.stdout)
        payload["parse_exit_code"] = parsed.returncode
    return payload


def launch_container(image_tag: str) -> dict:
    result = run_cmd(["docker", "run", "--rm", image_tag, "bash", "-lc", "echo launchability_ok"], timeout=30)
    return {"exit_code": result.returncode, "stdout": tail(result.stdout), "stderr": tail(result.stderr)}


def _runtime_source_strategy(rel_path: str, payload: dict) -> str:
    context_files = payload.get("build_context_files") if isinstance(payload.get("build_context_files"), dict) else {}
    if f"task_file/{rel_path}" in context_files:
        return "inline_build_context"
    if Path(rel_path).name == ".gitkeep":
        return "empty_directory_marker"
    return "generated_or_downloaded_during_build"


def _runtime_file_kind(rel_path: str) -> str:
    suffix = Path(rel_path).suffix.lower().lstrip(".")
    if suffix:
        return suffix
    return "file"


def _filter_runtime_rel_path(rel_path: str) -> bool:
    path = rel_path.strip("/")
    if not path or path == ".":
        return False
    parts = Path(path).parts
    if not parts:
        return False
    if parts[0] in {"build_scripts", "__pycache__", ".git", ".cache"}:
        return False
    if any(part == "__pycache__" for part in parts):
        return False
    if Path(path).name == ".gitkeep":
        return False
    return True


def _normalize_runtime_inventory(raw: dict, root: str, payload: dict) -> dict:
    entries = []
    for item in raw.get("entries") or []:
        if not isinstance(item, dict):
            continue
        rel = str(item.get("path") or "").strip("/")
        if not _filter_runtime_rel_path(rel):
            continue
        size = item.get("size_bytes")
        entries.append(
            {
                "path": rel,
                "absolute_path": f"{root.rstrip('/')}/{rel}",
                "kind": _runtime_file_kind(rel),
                "size_bytes": int(size) if isinstance(size, int) or str(size).isdigit() else None,
                "source_strategy": _runtime_source_strategy(rel, payload),
            }
        )
    directories = []
    for item in raw.get("directories") or []:
        rel = str(item.get("path") if isinstance(item, dict) else item).strip("/")
        if not _filter_runtime_rel_path(rel):
            continue
        directories.append({"path": rel, "absolute_path": f"{root.rstrip('/')}/{rel}"})
    entries = sorted(entries, key=lambda item: item["path"])
    directories = sorted(directories, key=lambda item: item["path"])
    return {
        "collected": bool(raw.get("collected", True)),
        "collection_method": raw.get("collection_method", "docker_runtime_scan"),
        "task_root": root,
        "entries": entries,
        "task_files": entries,
        "task_file_paths": [item["absolute_path"] for item in entries],
        "relative_task_file_paths": [item["path"] for item in entries],
        "task_directories": directories,
        "task_directory_paths": [item["absolute_path"] for item in directories],
        "relative_task_directory_paths": [item["path"] for item in directories],
        "filtered": {
            "build_scripts": True,
            "gitkeep_markers": True,
            "python_caches": True,
        },
    }


def collect_runtime_inventory_from_image(cfg: dict, image_tag: str, payload: dict) -> dict:
    root = task_root(cfg)
    script = r"""
import json
import os
root = os.environ.get("TASK_ROOT", "/task_file")
entries = []
directories = []
if os.path.isdir(root):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(name for name in dirnames if name not in {"build_scripts", "__pycache__", ".git", ".cache"})
        rel_dir = os.path.relpath(dirpath, root)
        if rel_dir != ".":
            directories.append({"path": rel_dir})
        for filename in sorted(filenames):
            rel = os.path.relpath(os.path.join(dirpath, filename), root)
            try:
                size = os.path.getsize(os.path.join(dirpath, filename))
            except OSError:
                size = None
            entries.append({"path": rel, "size_bytes": size})
print(json.dumps({"collected": True, "collection_method": "docker_runtime_scan", "entries": entries, "directories": directories}, sort_keys=True))
"""
    result = run_cmd(
        ["docker", "run", "--rm", "-e", f"TASK_ROOT={root}", image_tag, "python3", "-c", script],
        timeout=int(cfg.get("runtime_inventory_timeout_sec", 120)),
    )
    raw = _json_from_stdout(result.stdout)
    raw["exit_code"] = result.returncode
    raw["stderr"] = tail(result.stderr)
    if result.returncode != 0:
        raw["collected"] = False
    return _normalize_runtime_inventory(raw, root, payload)


def collect_runtime_inventory_from_local(ctx: RunContext, cfg: dict, task_id: str, payload: dict) -> dict:
    root = task_root(cfg)
    task_dir = candidate_dir(ctx, task_id) / "environment" / "task_file"
    entries = []
    directories = []
    if task_dir.exists():
        for dirpath, dirnames, filenames in os.walk(task_dir):
            dirnames[:] = sorted(name for name in dirnames if name not in {"build_scripts", "__pycache__", ".git", ".cache"})
            rel_dir = os.path.relpath(dirpath, task_dir)
            if rel_dir != ".":
                directories.append({"path": rel_dir})
            for filename in sorted(filenames):
                file_path = Path(dirpath) / filename
                rel = os.path.relpath(file_path, task_dir)
                entries.append({"path": rel, "size_bytes": file_path.stat().st_size})
    return _normalize_runtime_inventory({"collected": bool(task_dir.exists()), "collection_method": "local_environment_scan", "entries": entries, "directories": directories}, root, payload)


def verify_env_checks(ctx: RunContext, cfg: dict, task_id: str, image_tag: str, checks: list[str]) -> dict:
    metadata_dir = candidate_dir(ctx, task_id) / "pipeline_artifacts" / "environment" / "build_runtime"
    metadata_dir.mkdir(parents=True, exist_ok=True)
    checks_file = metadata_dir / "env_checks.json"
    output_file = metadata_dir / "env_check_results.json"
    effective_checks = checks or [f"test -d {task_root(cfg)}"]
    write_json(checks_file, effective_checks)
    result = run_cmd(
        [
            sys.executable,
            str(TOOL_DIR / "verify_env_checks.py"),
            "--image-tag",
            image_tag,
            "--checks-file",
            str(checks_file),
            "--output-file",
            str(output_file),
            "--task-root",
            task_root(cfg),
            "--timeout",
            str(int(cfg.get("smoke_check_timeout_sec", 60))),
            "--max-checks",
            str(int(cfg.get("max_env_checks", 8))),
        ],
        timeout=int(cfg.get("smoke_check_timeout_sec", 60)) * max(1, min(len(effective_checks), int(cfg.get("max_env_checks", 8)))) + 90,
    )
    payload = _json_from_stdout(result.stdout)
    payload["exit_code"] = result.returncode
    payload["stderr"] = tail(result.stderr)
    payload["output_file"] = str(output_file)
    payload["checks_file"] = str(checks_file)
    return payload


def maturity_profile(ctx: RunContext, cfg: dict, task_id: str, report: dict, written: list[str]) -> dict:
    build = report.get("build") if isinstance(report.get("build"), dict) else {}
    launch = report.get("launch") if isinstance(report.get("launch"), dict) else {}
    smoke = report.get("smoke") if isinstance(report.get("smoke"), dict) else {}
    buildability = bool(report.get("build_checked") and build.get("success"))
    launchability = bool(report.get("launch_checked") and launch.get("exit_code") == 0)
    fixture_readiness = bool(report.get("smoke_checked") and smoke.get("exit_code") == 0)
    level = "NotBuildable"
    if buildability:
        level = "Buildability"
    if launchability:
        level = "Launchability"
    if fixture_readiness:
        level = "FixtureReadiness"
    return {
        "Buildability": buildability,
        "Launchability": launchability,
        "FixtureReadiness": fixture_readiness,
        "level": level,
    }


def repair_payload_from_model(
    ctx: RunContext,
    cfg: dict,
    model_client: ModelClient,
    unit: dict,
    payload: dict,
    report: dict,
    failure_type: str,
    attempt: int,
) -> tuple[dict, str | None]:
    task_id = str(unit["task_id"])
    root = task_root(cfg)
    dockerfile = candidate_dir(ctx, task_id) / "environment" / "Dockerfile"
    context_files = payload.get("build_context_files") if isinstance(payload.get("build_context_files"), dict) else {}
    context = {
        "instruction_ref": instruction_ref_text(ctx, task_id),
        "dockerfile": dockerfile.read_text(encoding="utf-8") if dockerfile.exists() else "",
        "build_context_files": context_files,
        "parsed_log": report.get("build", {}).get("parsed_log") if isinstance(report.get("build"), dict) else report.get("lint") or report.get("smoke") or {},
        "failure_type": failure_type,
        "constraints": {"task_root": root, "base_image": base_image(ctx, cfg), "prompt_version": PROMPT_VERSION},
    }
    prompt = render_prompt(ENV_REPAIR_USER_PROMPT, context, task_root=root, base_image=base_image(ctx, cfg))
    log_dir = stage_log_dir(ctx, "env_build", task_id)
    write_text(log_dir / f"repair_prompt_{attempt}.txt", prompt)
    repaired, call_id = model_client.chat_json("facet_terminal_env_repair", str(unit.get("pair_id", task_id)), "", prompt, None)
    write_json(log_dir / f"repair_payload_{attempt}.json", repaired)
    return repaired, call_id


def merge_repair_payload(payload: dict, repair: dict) -> dict:
    merged = dict(payload)
    if isinstance(repair.get("dockerfile"), str) and repair["dockerfile"].strip():
        merged["dockerfile"] = repair["dockerfile"]
    if isinstance(repair.get("env_checks"), list):
        merged["env_checks"] = [str(item) for item in repair["env_checks"]]
    context_files = dict(merged.get("build_context_files") or {}) if isinstance(merged.get("build_context_files"), dict) else {}
    if isinstance(repair.get("delete_files"), list):
        for raw_path in repair["delete_files"]:
            rel = normalize_build_context_path(str(raw_path), "/task_file")
            context_files.pop(rel, None)
            context_files.pop(str(raw_path), None)
    patch = repair.get("build_context_files_patch")
    if isinstance(patch, dict):
        for raw_path, content in patch.items():
            rel = normalize_build_context_path(str(raw_path), "/task_file")
            context_files[rel] = content if isinstance(content, str) else json.dumps(content, ensure_ascii=False, indent=2) + "\n"
    merged["build_context_files"] = context_files
    return merged


def env_build_one(ctx: RunContext, cfg: dict, model_client: ModelClient | None, unit: dict) -> dict:
    task_id = str(unit["task_id"])
    report = {"task_id": task_id, "status": "env_build_failed"}
    try:
        mode = str(cfg.get("mode", "llm"))
        if mode == "template":
            payload = template_env_payload(unit, task_root(cfg))
            profile = None
            call_id = None
        else:
            if model_client is None:
                raise ValueError("model_client_required_for_llm_env")
            payload, profile, call_id = env_payload_from_model(ctx, cfg, model_client, unit)
        payload = normalize_env_payload(unit, payload, task_root(cfg), base_image(ctx, cfg))
        max_repairs = int(cfg.get("repair_attempts", 2))
        repair_history: list[dict] = []
        written: list[str] = []
        for attempt in range(max_repairs + 1):
            clear_env_outputs(ctx, task_id)
            written = write_env_payload(ctx, cfg, unit, payload)
            report = {
                "task_id": task_id,
                "status": "env_build_ready",
                "mode": mode,
                "model_profile": profile,
                "model_call_id": call_id,
                "attempt": attempt,
                "repair_history": repair_history,
                "written": written,
                "build_checked": False,
                "launch_checked": False,
                "smoke_checked": False,
            }
            failure_type = ""
            lint = lint_dockerfile(ctx, task_id)
            report["lint_checked"] = True
            report["lint"] = lint
            if lint.get("has_errors"):
                failure_type = "dockerfile_lint_failed"
            if not failure_type and bool(cfg.get("build_enabled", False)):
                image_tag = f"facet-terminal-{ctx.run_id}-{task_id}".lower().replace("_", "-")
                build = build_dockerfile(ctx, cfg, task_id, image_tag)
                report["build_checked"] = True
                report["build"] = build
                if build.get("exit_code") != 0 or not build.get("success"):
                    failure_type = "build_failed"
                else:
                    launch = launch_container(image_tag)
                    report["launch_checked"] = True
                    report["launch"] = launch
                    if launch.get("exit_code") != 0:
                        failure_type = "launch_failed"
                    else:
                        report["runtime_inventory"] = collect_runtime_inventory_from_image(cfg, image_tag, payload)
                        checks, skipped_checks = smoke_checks(payload)
                        if skipped_checks:
                            report["skipped_env_checks"] = skipped_checks
                        smoke = verify_env_checks(ctx, cfg, task_id, image_tag, checks)
                        report["smoke_checked"] = True
                        report["smoke"] = smoke
                        if smoke.get("exit_code") != 0:
                            failure_type = "setup_failed"
                    if cfg.get("remove_images", True):
                        run_cmd(["docker", "rmi", "-f", image_tag], timeout=90)
            elif not failure_type:
                report["runtime_inventory"] = collect_runtime_inventory_from_local(ctx, cfg, task_id, payload)
            report["maturity"] = maturity_profile(ctx, cfg, task_id, report, written)
            if not failure_type:
                break
            report["status"] = "env_build_failed"
            report["failure_type"] = failure_type
            if attempt >= max_repairs or model_client is None or mode == "template":
                raise RuntimeError(failure_type)
            repaired, repair_call_id = repair_payload_from_model(ctx, cfg, model_client, unit, payload, report, failure_type, attempt + 1)
            repair_history.append(
                {
                    "attempt": attempt + 1,
                    "failure_type": failure_type,
                    "model_call_id": repair_call_id,
                    "repair_notes": repaired.get("repair_notes", ""),
                    "allowed_fields_modified": [key for key in ("dockerfile", "build_context_files_patch", "delete_files", "env_checks") if key in repaired],
                }
            )
            payload = normalize_env_payload(unit, merge_repair_payload(payload, repaired), task_root(cfg), base_image(ctx, cfg))
        real_env_file_summary = build_real_env_file_summary(cfg, payload, report, written)
        writer = ArtifactWriter(ctx, STAGE)
        summary_path = writer.write_json(task_id, REAL_ENV_FILE_SUMMARY_PATH, real_env_file_summary)
        written.append(REAL_ENV_FILE_SUMMARY_PATH)
        report["real_env_file_summary"] = real_env_file_summary
        report["real_env_file_summary_path"] = summary_path
        report["env_build_manifest"] = real_env_file_summary
        report["env_build_manifest_path"] = summary_path
        report["written"] = written
        write_json(stage_report_dir(ctx, STAGE) / f"{task_id}.json", report)
        record_event(ctx, task_id, STAGE, "env_build_ready")
        row = dict(unit)
        row["env_build"] = report
        row["real_env_file_summary"] = real_env_file_summary
        row["env_build_manifest"] = real_env_file_summary
        row["env"] = report
        return {"status": "env_build_ready", "task_id": task_id, "unit": row}
    except Exception as exc:
        report.update({"status": "env_build_failed", "failure_type": str(exc), "error": repr(exc)})
        write_json(stage_report_dir(ctx, STAGE) / f"{task_id}.json", report)
        record_event(ctx, task_id, STAGE, "env_build_failed", error=repr(exc))
        return {"status": "env_build_failed", "task_id": task_id, "failure_type": str(exc), "unit": unit}


def run(ctx: RunContext, args: argparse.Namespace) -> None:
    stage = STAGE
    started = utc_now()
    cfg = stage_cfg(ctx, stage)
    input_path = ctx.path(str(cfg.get("input_jsonl", "artifacts/facet_terminal/instruction_ref_units.jsonl")))
    output_path = ctx.path(str(cfg.get("output_jsonl", "artifacts/facet_terminal/env_build_units.jsonl")))
    units = read_jsonl(input_path)
    if args.limit:
        units = units[: args.limit]
    workers = worker_count(ctx, stage, cfg, args.workers)
    batch_size = int(cfg.get("batch_size", 4))
    model_client = ModelClient(ctx) if str(cfg.get("mode", "llm")) != "template" else None
    results = run_batched("facet_terminal_env_build:build", units, workers, batch_size, int(cfg.get("max_inflight_batches", 2)), lambda unit: env_build_one(ctx, cfg, model_client, unit))
    ready = [row["unit"] for row in results if row.get("status") == "env_build_ready"]
    write_jsonl(output_path, ready)
    summary = {"input_count": len(units), "env_build_ready": len(ready), "env_build_failed": len(results) - len(ready)}
    write_stage_report(ctx, stage, started, {"instruction_ref_units": {"path": str(input_path.relative_to(ctx.run_dir)), "hash": file_hash(input_path)}}, {"env_build_units": {"path": str(output_path.relative_to(ctx.run_dir)), "records": len(ready), "hash": file_hash(output_path)}}, summary, cfg)
