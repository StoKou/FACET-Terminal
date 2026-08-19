from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .hashing import canonical_json, sha256_text
from .io import append_jsonl, load_config, read_json, write_json


SCHEMA_VERSION = "v1"
PIPELINE_VERSION = "facet-terminal"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class RunContext:
    config_path: Path
    config: dict[str, Any]
    run_id: str
    run_dir: Path

    @classmethod
    def from_config(cls, config_path: Path, run_id: str | None = None) -> "RunContext":
        config_path = config_path.resolve()
        config = load_config(config_path)
        run_cfg = config.get("run", {})
        root = Path(run_cfg.get("root_dir", "runs"))
        if not root.is_absolute():
            root = config_path.parent.parent / root
        resolved_run_id = run_id or run_cfg.get("run_id") or datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        ctx = cls(config_path=config_path, config=config, run_id=str(resolved_run_id), run_dir=root / str(resolved_run_id))
        ctx.clear_proxy_env()
        ctx.ensure_layout()
        return ctx

    def clear_proxy_env(self) -> None:
        for key in ["HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY", "http_proxy", "https_proxy", "all_proxy", "no_proxy"]:
            os.environ.pop(key, None)

    def ensure_layout(self) -> None:
        for rel in ["final", "artifacts", "cache", "checkpoints", "reports", "manifests", "logs", "tmp", "debug"]:
            self.path(rel).mkdir(parents=True, exist_ok=True)

    def path(self, rel: str) -> Path:
        return self.run_dir / rel

    def config_hash(self) -> str:
        return sha256_text(canonical_json(self.config))

    def event(self, stage: str, name: str, **data: Any) -> None:
        append_jsonl(
            self.path("logs/events.jsonl"),
            {"schema_version": SCHEMA_VERSION, "run_id": self.run_id, "stage": stage, "event": name, "created_at": utc_now(), **data},
        )

    def manifest(
        self,
        stage: str,
        status: str,
        started_at: str,
        inputs: dict[str, Any],
        outputs: dict[str, Any],
        summary: dict[str, Any],
        validator: dict[str, Any],
        parameters: dict[str, Any] | None = None,
        reason: str | None = None,
    ) -> None:
        finished_at = utc_now()
        payload = {
            "schema_version": SCHEMA_VERSION,
            "stage": stage,
            "status": status,
            "reason": reason,
            "started_at": started_at,
            "finished_at": finished_at,
            "config_hash": self.config_hash(),
            "input_hash": sha256_text(canonical_json(inputs)),
            "output_hash": sha256_text(canonical_json(outputs)),
            "parameters": parameters or {},
            "inputs": inputs,
            "outputs": outputs,
            "summary": summary,
            "validator": validator,
            "model_calls": {"call_log_path": "logs/model_calls.jsonl"},
        }
        write_json(self.path(f"manifests/{stage}_manifest.json"), payload)
        state_path = self.path("manifests/stage_state.json")
        state = read_json(state_path) if state_path.exists() else {"schema_version": SCHEMA_VERSION, "run_id": self.run_id, "stages": {}}
        state["stages"][stage] = {"status": status, "manifest": f"manifests/{stage}_manifest.json", "finished_at": finished_at}
        write_json(state_path, state)
