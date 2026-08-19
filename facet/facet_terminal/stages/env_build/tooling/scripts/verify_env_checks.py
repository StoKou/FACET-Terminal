#!/usr/bin/env python3
"""Run environment readiness checks against a built Docker image.

The checks are environment probes only: file existence, lightweight parsing,
and command availability. They are executed one by one in a temporary
container so failures can be reported with useful detail.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path


BANNED_PATH_PREFIXES = ("/opt/mock", "/mock", "/tmp/mock", "/app/mock")


def run_cmd(args: list[str], timeout: int) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, text=True, capture_output=True, timeout=timeout, check=False)


def load_checks(path: Path, max_checks: int, task_root: str) -> list[str]:
    checks = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(checks, list):
        raise ValueError("checks file must contain a JSON array")
    normalized = [str(item).strip() for item in checks if str(item).strip()]
    if not normalized:
        normalized = [f"test -d {task_root}"]
    return normalized[: max(1, max_checks)]


def command_probe_name(check: str) -> str | None:
    match = re.search(r"\b(?:command\s+-v|which)\s+([A-Za-z0-9_.+-]+)", check)
    return match.group(1) if match else None


def authenticity_warning(check: str, stdout: str) -> dict | None:
    if not command_probe_name(check):
        return None
    path = stdout.strip().splitlines()[0] if stdout.strip() else ""
    if not path:
        return None
    if path.startswith(BANNED_PATH_PREFIXES):
        return {"check": check, "path": path, "warning": "command resolves to banned mock-like path"}
    return None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--image-tag", required=True)
    parser.add_argument("--checks-file", required=True)
    parser.add_argument("--output-file")
    parser.add_argument("--task-root", default="/task_file")
    parser.add_argument("--timeout", type=int, default=60)
    parser.add_argument("--max-checks", type=int, default=8)
    args = parser.parse_args()

    container_name = ""
    results: list[dict] = []
    warnings: list[dict] = []
    try:
        checks = load_checks(Path(args.checks_file), args.max_checks, args.task_root)
        launch = run_cmd(["docker", "run", "-d", args.image_tag, "sleep", "infinity"], timeout=30)
        if launch.returncode != 0:
            payload = {
                "success": False,
                "exit_code": launch.returncode,
                "stage": "launch",
                "stdout": launch.stdout[-4000:],
                "stderr": launch.stderr[-4000:],
                "checks": checks,
                "results": [],
                "authenticity_warnings": [],
            }
            emit(payload, args.output_file)
            sys.exit(1)
        container_name = launch.stdout.strip()
        for index, check in enumerate(checks, 1):
            proc = run_cmd(["docker", "exec", container_name, "bash", "-lc", check], timeout=args.timeout)
            result = {
                "index": index,
                "check": check,
                "exit_code": proc.returncode,
                "stdout": proc.stdout[-4000:],
                "stderr": proc.stderr[-4000:],
            }
            warning = authenticity_warning(check, proc.stdout)
            if warning:
                warnings.append(warning)
            results.append(result)
        success = all(item["exit_code"] == 0 for item in results)
        payload = {
            "success": success,
            "exit_code": 0 if success else 1,
            "stage": "checks",
            "checks": checks,
            "results": results,
            "failed": [item for item in results if item["exit_code"] != 0],
            "authenticity_warnings": warnings,
        }
        emit(payload, args.output_file)
        sys.exit(0 if success else 1)
    except subprocess.TimeoutExpired as exc:
        payload = {
            "success": False,
            "exit_code": 124,
            "stage": "timeout",
            "error": str(exc),
            "results": results,
            "authenticity_warnings": warnings,
        }
        emit(payload, args.output_file)
        sys.exit(124)
    except Exception as exc:
        payload = {
            "success": False,
            "exit_code": 2,
            "stage": "error",
            "error": repr(exc),
            "results": results,
            "authenticity_warnings": warnings,
        }
        emit(payload, args.output_file)
        sys.exit(2)
    finally:
        if container_name:
            run_cmd(["docker", "rm", "-f", container_name], timeout=30)


def emit(payload: dict, output_file: str | None) -> None:
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    if output_file:
        Path(output_file).write_text(text + "\n", encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
