#!/usr/bin/env python3
"""Static linter for Dockerfiles — catch definite build failures before building.

Checks only for issues that will deterministically cause the build to fail or
hang. Does not check style, preferences, or best-practice hints — those are
the agent's domain.

Checks performed:
  no_from        — Dockerfile missing FROM instruction (always invalid)
  apt_no_yes     — apt-get install without -y (build will hang)
  yum_no_yes     — yum/dnf install without -y (build will hang)
  apt_no_update  — apt-get install without apt-get update (packages not found)

Usage:
    python3 scripts/lint_dockerfile.py /path/to/Dockerfile

Output: JSON with errors array. Exit code 0 = no blockers, 1 = has blockers.

{
  "path": "/path/to/Dockerfile",
  "errors": [
    {"line": 5, "rule": "apt_no_update",
     "message": "apt-get install without apt-get update — packages will not be found"}
  ],
  "has_errors": false
}
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def lint(dockerfile_path: str) -> dict:
    path = Path(dockerfile_path)
    if not path.exists():
        return {"path": str(path), "error": "File not found", "errors": [],
                "has_errors": False}

    text = path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    errors: list[dict] = []

    def error(line: int, rule: str, message: str) -> None:
        errors.append({"line": line, "rule": rule, "message": message})

    has_from = False
    from_line = 0
    uses_apt = False
    has_apt_update = False
    run_blocks: list[tuple[int, str]] = []

    continued = ""
    cont_start = 0

    for i, raw_line in enumerate(lines, 1):
        stripped = raw_line.strip()

        if stripped.startswith("#") or not stripped:
            continue

        if continued:
            continued += " " + stripped.rstrip("\\").strip()
            if not stripped.endswith("\\"):
                run_blocks.append((cont_start, continued))
                continued = ""
            continue

        upper = stripped.split()[0].upper() if stripped.split() else ""

        if upper == "FROM":
            has_from = True
            from_line = i

        elif upper == "RUN":
            body = stripped[3:].strip().rstrip("\\").strip()
            if stripped.endswith("\\"):
                continued = body
                cont_start = i
            else:
                run_blocks.append((i, body))

    if not has_from:
        error(1, "no_from", "Dockerfile has no FROM instruction")

    for line_no, body in run_blocks:
        lower = body.lower()

        if "apt-get install" in lower or "apt install" in lower:
            uses_apt = True
            if "apt-get update" in lower or "apt update" in lower:
                has_apt_update = True
            if "-y" not in lower and "--yes" not in lower:
                error(line_no, "apt_no_yes",
                      "apt-get install without -y flag — build will hang "
                      "waiting for confirmation")

        if "yum install" in lower or "dnf install" in lower:
            if "-y" not in lower:
                error(line_no, "yum_no_yes",
                      "yum/dnf install without -y flag — build will hang")

    if uses_apt and not has_apt_update:
        error(from_line or 1, "apt_no_update",
              "apt-get install without apt-get update — packages will not be found")

    return {
        "path": str(path),
        "errors": errors,
        "has_errors": len(errors) > 0,
    }


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: lint_dockerfile.py <Dockerfile-path>", file=sys.stderr)
        sys.exit(2)

    result = lint(sys.argv[1])
    print(json.dumps(result, ensure_ascii=False, indent=2))

    if result.get("has_errors"):
        sys.exit(1)


if __name__ == "__main__":
    main()
