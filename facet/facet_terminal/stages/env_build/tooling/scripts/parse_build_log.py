#!/usr/bin/env python3
"""Extract structural info from a docker build log.

Deterministic extraction only — no error classification, no suggested fixes.
The agent reads the log file directly and decides how to respond. This script
saves the agent from parsing step numbers and error line positions itself.

Usage:
    python3 scripts/parse_build_log.py --log-file build.log

    docker build -t img . 2>&1 | python3 scripts/parse_build_log.py

Output JSON:
{
  "failed_step": 5,
  "failed_line": "RUN apt-get install -y libfoo-dev",
  "error_tail": "...last ~500 chars of lines containing error keywords..."
}
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path


def _extract_failed_step(log: str) -> tuple[int | None, str]:
    """Extract the step number and RUN line that failed."""
    step_match = re.findall(
        r"(?:Step|#)[\s]*(\d+)[\s/\d]*:?\s*(RUN .+?)(?:\n|$)",
        log, re.IGNORECASE,
    )
    if step_match:
        last = step_match[-1]
        return int(last[0]), last[1].strip()

    run_match = re.findall(r"(RUN .+?)(?:\n|$)", log)
    if run_match:
        return None, run_match[-1].strip()

    return None, ""


def _extract_error_tail(log: str, max_chars: int = 500) -> str:
    """Return the last lines that contain error-related keywords."""
    error_lines = []
    for line in log.splitlines():
        lower = line.lower()
        if any(kw in lower for kw in (
            "error", "failed", "fatal", "unable", "not found",
            "cannot", "killed", "denied", "no such", "no match",
        )):
            error_lines.append(line.strip())
    tail = "\n".join(error_lines[-20:]) if error_lines else log[-max_chars:]
    return tail[-max_chars:]


def parse(log: str) -> dict:
    """Extract structural info from a docker build log."""
    step_no, failed_line = _extract_failed_step(log)
    error_tail = _extract_error_tail(log)
    return {
        "failed_step": step_no,
        "failed_line": failed_line[:300] if failed_line else "",
        "error_tail": error_tail,
    }


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description="Extract structural info from a docker build log.",
    )
    parser.add_argument("--log-file", default="",
                        help="Path to build log file (default: read stdin)")
    args = parser.parse_args()

    if args.log_file:
        log = Path(args.log_file).read_text(encoding="utf-8", errors="replace")
    else:
        log = sys.stdin.read()

    if not log.strip():
        print(json.dumps({"error": "Empty log input"}))
        sys.exit(1)

    result = parse(log)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
