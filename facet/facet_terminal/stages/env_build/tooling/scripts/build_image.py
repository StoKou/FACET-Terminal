#!/usr/bin/env python3
"""Build a Docker image with integrated logging and retry tracking.

Wraps `docker build` + log capture into one atomic operation. The agent
calls this once per build attempt instead of running three separate commands.

The build step always uses `docker build` regardless of whether a
docker-compose.yaml is present.  Compose services (postgres, redis, etc.)
are pre-built images that get pulled at runtime by `docker compose up` in
Step 4 — they do not need to be built here.  The output JSON includes a
`compose_mode` flag so downstream steps know which verification strategy
to use.

Usage:
    python3 scripts/build_image.py \
        --image-tag facet-env-000001 \
        --dockerfile-dir /path/to/output \
        [--cache-from facet-env-000001] \
        [--network default] \
        [--no-cache] \
        [--build-timeout 1200]

Output JSON (stdout):
{
  "success": true,
  "exit_code": 0,
  "attempt": 1,
  "duration_s": 45.2,
  "image_tag": "facet-env-000001",
  "image_size_mb": 342.5,
  "log_file": "/path/to/output/build.log",
  "compose_mode": false
}

On failure, "log_file" contains the full build output for the agent to read
and diagnose.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path


_ATTEMPT_FILE = ".build_attempt_count"
_METADATA_FILE = "build_metadata.json"
_MATURITY_LEVEL_KEY = "maturity_level"


def _read_attempt(metadata_dir: Path) -> int:
    counter_file = metadata_dir / _ATTEMPT_FILE
    if counter_file.exists():
        try:
            return int(counter_file.read_text().strip())
        except (ValueError, OSError):
            return 0
    return 0


def _write_attempt(metadata_dir: Path, attempt: int) -> None:
    metadata_dir.mkdir(parents=True, exist_ok=True)
    (metadata_dir / _ATTEMPT_FILE).write_text(str(attempt), encoding="utf-8")


def _update_build_metadata(metadata_dir: Path, maturity_level: str) -> None:
    metadata_dir.mkdir(parents=True, exist_ok=True)
    metadata_path = metadata_dir / _METADATA_FILE
    metadata: dict = {}
    if metadata_path.exists():
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            metadata = {}

    metadata[_MATURITY_LEVEL_KEY] = maturity_level
    metadata_path.write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _get_image_size(image_tag: str) -> float | None:
    """Get image size in MB."""
    try:
        result = subprocess.run(
            ["docker", "image", "inspect", image_tag,
             "--format", "{{.Size}}"],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode == 0:
            size_bytes = int(result.stdout.strip())
            return round(size_bytes / (1024 * 1024), 1)
    except (subprocess.TimeoutExpired, ValueError, OSError):
        pass
    return None


def _has_compose(dockerfile_dir: Path) -> bool:
    return any(
        (dockerfile_dir / n).exists()
        for n in ("docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml")
    )


def _record_artifact_history(dockerfile_dir: Path, metadata_dir: Path, attempt: int, success: bool):
    """Silently append the current Dockerfile and Compose contents to the history log"""
    try:
        from datetime import datetime, timezone
        import json

        files = {}
        for name in ("Dockerfile", "docker-compose.yaml", "docker-compose.yml", "compose.yaml", "compose.yml"):
            path = dockerfile_dir / name
            if path.exists():
                files[name] = path.read_text(encoding="utf-8")

        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "attempt": attempt,
            "success": success,
            "files": files
        }

        metadata_dir.mkdir(parents=True, exist_ok=True)
        history_path = metadata_dir / "artifact_history.jsonl"
        with open(history_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception:
        pass


def build(
    image_tag: str,
    dockerfile_dir: Path,
    metadata_dir: Path | None = None,
    cache_from: str | None = None,
    no_cache: bool = False,
    build_timeout: int = 1200,
    network: str | None = None,
) -> dict:
    """Build Docker image and return structured result."""
    runtime_dir = metadata_dir or dockerfile_dir
    runtime_dir.mkdir(parents=True, exist_ok=True)
    attempt = _read_attempt(runtime_dir) + 1
    _write_attempt(runtime_dir, attempt)

    log_file = runtime_dir / "build.log"
    compose_mode = _has_compose(dockerfile_dir)

    env = os.environ.copy()
    env["DOCKER_BUILDKIT"] = "0"

    cmd = [
        "docker", "build", "-t", image_tag,
        "--build-arg", "BUILDKIT_INLINE_CACHE=1",
    ]
    if network:
        cmd += ["--network", network]
    if no_cache:
        cmd.append("--no-cache")
    if cache_from and not no_cache:
        cmd += ["--cache-from", cache_from]
    cmd.append(".")

    start_time = time.time()
    exit_code = 0

    with open(log_file, "w", encoding="utf-8") as f:
        f.write(f"--- Running: {' '.join(cmd)} ---\n")
        f.flush()
        os.fsync(f.fileno())

        process = subprocess.Popen(
            cmd,
            stdout=f,
            stderr=subprocess.STDOUT,
            env=env,
            cwd=str(dockerfile_dir),
        )

        try:
            process.communicate(timeout=build_timeout)
            if process.returncode != 0:
                exit_code = process.returncode
        except subprocess.TimeoutExpired:
            exit_code = 124
            process.terminate()
            try:
                process.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.communicate()

            f.flush()
            os.fsync(f.fileno())
            f.write(f"\n\n--- BUILD TIMED OUT after {build_timeout}s ---\n")
            f.flush()
            os.fsync(f.fileno())

    duration = round(time.time() - start_time, 1)

    if exit_code == 0:
        image_size = _get_image_size(image_tag)
        _update_build_metadata(runtime_dir, "Buildability")

        _record_artifact_history(dockerfile_dir, runtime_dir, attempt, success=True)

        return {
            "success": True,
            "exit_code": 0,
            "attempt": attempt,
            "duration_s": duration,
            "image_tag": image_tag,
            "image_size_mb": image_size,
            "log_file": str(log_file),
            "compose_mode": compose_mode,
        }

    _record_artifact_history(dockerfile_dir, runtime_dir, attempt, success=False)

    return {
        "success": False,
        "exit_code": exit_code,
        "attempt": attempt,
        "duration_s": duration,
        "image_tag": image_tag,
        "image_size_mb": None,
        "log_file": str(log_file),
        "compose_mode": compose_mode,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build Docker image with integrated logging.",
    )
    parser.add_argument("--image-tag", required=True,
                        help="Docker image tag (e.g. facet-env-000001)")
    parser.add_argument("--dockerfile-dir", required=True,
                        help="Directory containing the Dockerfile")
    parser.add_argument("--metadata-dir", default=None,
                        help="Directory for build logs, attempt counters, metadata, and artifact history")
    parser.add_argument("--network", default=None,
                        help="Docker build network mode")
    parser.add_argument("--cache-from", default=None,
                        help="Image to use as build cache source")
    parser.add_argument("--no-cache", action="store_true", default=False,
                        help="Build without cache (overrides --cache-from)")
    parser.add_argument("--build-timeout", type=int, default=1200,
                        help="Build timeout in seconds (default: 1200)")
    args = parser.parse_args()

    dockerfile_dir = Path(args.dockerfile_dir)
    if not (dockerfile_dir / "Dockerfile").exists():
        print(json.dumps({"error": f"No Dockerfile in {dockerfile_dir}"}))
        sys.exit(1)

    result = build(
        image_tag=args.image_tag,
        dockerfile_dir=dockerfile_dir,
        metadata_dir=Path(args.metadata_dir) if args.metadata_dir else None,
        cache_from=args.cache_from,
        no_cache=args.no_cache,
        build_timeout=args.build_timeout,
        network=args.network,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))

    sys.exit(0 if result["success"] else 1)


if __name__ == "__main__":
    main()
