from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from typing import Any

os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "true")
import litellm

from .context import SCHEMA_VERSION, RunContext, utc_now
from .hashing import canonical_json, sha256_text, short_hash
from .io import append_jsonl


class ModelError(RuntimeError):
    pass


def _post_json(url: str, payload: dict[str, Any], api_key: str, timeout: int) -> dict[str, Any]:
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(req, timeout=timeout) as response:
        raw = response.read().decode("utf-8")
    return json.loads(raw)


def _redact_url(url: str) -> str:
    if "://" not in url:
        return url
    scheme, rest = url.split("://", 1)
    host = rest.split("/", 1)[0]
    if len(host) <= 12:
        safe_host = host
    else:
        safe_host = host[:10] + "..."
    return f"{scheme}://{safe_host}/..."


class ModelClient:
    def __init__(self, ctx: RunContext) -> None:
        self.ctx = ctx

    def _chat_config(self, stage: str, model_profile: str | None = None) -> dict[str, Any]:
        base = dict(self.ctx.config["model"]["chat"])
        profile_name = model_profile or self.ctx.config.get(stage, {}).get("model_profile") or base.get("profile")
        if not profile_name:
            return base
        profiles = self.ctx.config.get("model", {}).get("chat_profiles", {})
        if profile_name not in profiles:
            raise ModelError(f"unknown chat model profile: {profile_name}")
        merged = dict(base)
        profile = dict(profiles[profile_name])
        base_extra = dict(base.get("extra_body") or {})
        profile_extra = dict(profile.pop("extra_body", {}) or {})
        merged.update(profile)
        if base_extra or profile_extra:
            merged["extra_body"] = {**base_extra, **profile_extra}
        merged["profile"] = profile_name
        return merged

    @staticmethod
    def _api_key(cfg: dict[str, Any]) -> str:
        env_name = cfg.get("api_key_env")
        if env_name:
            return os.environ.get(str(env_name), str(cfg.get("api_key", "")))
        return str(cfg.get("api_key", ""))

    def chat_model_name(self, stage: str, model_profile: str | None = None) -> str:
        return str(self._chat_config(stage, model_profile).get("model_name", "chat"))

    def chat_json(self, stage: str, unit_id: str, system_prompt: str, user_prompt: str, model_profile: str | None = None) -> tuple[dict[str, Any], str]:
        cfg = self._chat_config(stage, model_profile)
        messages = [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}]
        completion_kwargs: dict[str, Any] = {
            "model": self._litellm_model_name(str(cfg["model_name"])),
            "base_url": cfg["api_base"].rstrip("/"),
            "api_key": self._api_key(cfg),
            "messages": messages,
            "temperature": cfg.get("temperature", 1.0),
            "max_tokens": cfg.get("max_tokens", 8192),
            "timeout": int(cfg.get("timeout_sec", 300)),
        }
        completion_kwargs.update(cfg.get("extra_body") or {})
        call_fingerprint = {
            "model": completion_kwargs["model"],
            "base_url": completion_kwargs["base_url"],
            "messages": messages,
            "temperature": completion_kwargs.get("temperature"),
            "max_tokens": completion_kwargs.get("max_tokens"),
            "extra_body": cfg.get("extra_body") or {},
            "model_profile": cfg.get("profile"),
        }
        call_id = "mc_" + short_hash(stage + "\n" + unit_id + "\n" + sha256_text(canonical_json(call_fingerprint)))
        started = time.monotonic()
        error: str | None = None
        response_hash = None
        parsed: dict[str, Any] | None = None
        attempts = int(cfg.get("max_retries", 1))
        for attempt in range(1, attempts + 1):
            try:
                # Some OpenAI-compatible proxies expose provider-specific
                # controls that
                # older LiteLLM/OpenAI SDK combinations reject before making
                # an HTTP request.  Keep LiteLLM as the default transport, but
                # allow an explicitly configured raw OpenAI request when the
                # proxy must receive such fields verbatim.
                if cfg.get("transport") == "raw_openai_http":
                    raw_payload = {
                        "model": str(cfg["model_name"]),
                        "messages": messages,
                        "temperature": cfg.get("temperature", 1.0),
                        "max_tokens": cfg.get("max_tokens", 8192),
                        **dict(cfg.get("extra_body") or {}),
                    }
                    raw_payload.pop("allowed_openai_params", None)
                    response = _post_json(
                        str(cfg["api_base"]).rstrip("/") + "/chat/completions",
                        raw_payload,
                        self._api_key(cfg),
                        int(cfg.get("timeout_sec", 300)),
                    )
                else:
                    response = litellm.completion(**completion_kwargs)
                content = self._message_content(response)
                response_hash = sha256_text(content)
                parsed = self._parse_json_content(content)
                break
            except Exception as exc:
                error = f"{type(exc).__name__}: {exc}"
                if attempt < attempts:
                    time.sleep(self._retry_wait_seconds(cfg, attempt))
        latency_ms = int((time.monotonic() - started) * 1000)
        append_jsonl(
            self.ctx.path("logs/model_calls.jsonl"),
            {
                "schema_version": SCHEMA_VERSION,
                "model_call_id": call_id,
                "run_id": self.ctx.run_id,
                "stage": stage,
                "call_name": f"{stage}.chat",
                "unit_id": unit_id,
                "model_type": "chat",
                "model_instance_id": cfg.get("model_name", "chat"),
                "api_base_redacted": _redact_url(cfg["api_base"]),
                "api_base_hash": sha256_text(cfg["api_base"]),
                "model_name": cfg["model_name"],
                "model_config_hash": sha256_text(canonical_json({k: v for k, v in cfg.items() if k != "api_key"})),
                "prompt": {"system_prompt_hash": sha256_text(system_prompt), "prompt_render_hash": sha256_text(user_prompt)},
                "response": {"response_hash": response_hash},
                "status": "success" if parsed is not None else "failed",
                "error_message": error,
                "latency_ms": latency_ms,
                "created_at": utc_now(),
                "client": {"library": "litellm", "model": completion_kwargs["model"]},
            },
        )
        if parsed is None:
            raise ModelError(error or "chat model returned no parseable JSON")
        return parsed, call_id

    def embeddings(self, stage: str, unit_id: str, texts: list[str]) -> tuple[list[list[float]], str]:
        cfg = self.ctx.config["model"]["embedding"]
        endpoint = cfg.get("endpoint", "/embeddings")
        url = cfg["api_base"].rstrip("/") + "/" + endpoint.lstrip("/")
        body = {"model": cfg["model"], "input": texts}
        call_id = "mc_" + short_hash(stage + "\n" + unit_id + "\n" + sha256_text(canonical_json(body)))
        started = time.monotonic()
        error: str | None = None
        vectors: list[list[float]] | None = None
        attempts = int(cfg.get("max_retries", 1))
        for attempt in range(1, attempts + 1):
            try:
                response = _post_json(url, body, cfg.get("api_key", ""), int(cfg.get("timeout_sec", 300)))
                data = response.get("data") or []
                vectors = [list(map(float, item["embedding"])) for item in sorted(data, key=lambda x: x.get("index", 0))]
                if len(vectors) != len(texts):
                    raise ModelError(f"embedding count mismatch: got {len(vectors)}, expected {len(texts)}")
                if cfg.get("l2_normalize", True):
                    vectors = [self._normalize(row) for row in vectors]
                break
            except Exception as exc:
                error = f"{type(exc).__name__}: {exc}"
                if attempt < attempts:
                    time.sleep(float(cfg.get("retry_min_wait_sec", 2)))
        latency_ms = int((time.monotonic() - started) * 1000)
        append_jsonl(
            self.ctx.path("logs/model_calls.jsonl"),
            {
                "schema_version": SCHEMA_VERSION,
                "model_call_id": call_id,
                "run_id": self.ctx.run_id,
                "stage": stage,
                "call_name": f"{stage}.embedding",
                "unit_id": unit_id,
                "model_type": "embedding",
                "model_instance_id": cfg.get("model", "embedding"),
                "api_base_redacted": _redact_url(cfg["api_base"]),
                "api_base_hash": sha256_text(cfg["api_base"]),
                "model_name": cfg["model"],
                "model_config_hash": sha256_text(canonical_json({k: v for k, v in cfg.items() if k != "api_key"})),
                "prompt": {"prompt_render_hash": sha256_text(canonical_json(texts))},
                "response": {"response_hash": sha256_text(canonical_json(vectors)) if vectors is not None else None},
                "status": "success" if vectors is not None else "failed",
                "error_message": error,
                "latency_ms": latency_ms,
                "created_at": utc_now(),
            },
        )
        if vectors is None:
            raise ModelError(error or "embedding model failed")
        return vectors, call_id

    @staticmethod
    def _parse_json_content(content: str) -> dict[str, Any]:
        text = content.strip()
        if text.startswith("```"):
            text = text.strip("`")
            if text.lower().startswith("json"):
                text = text[4:].strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            start = text.find("{")
            end = text.rfind("}")
            if start >= 0 and end > start:
                return json.loads(text[start : end + 1])
            raise

    @staticmethod
    def _litellm_model_name(model_name: str) -> str:
        if "/" in model_name:
            return model_name
        return f"openai/{model_name}"

    @staticmethod
    def _message_content(response: Any) -> str:
        if isinstance(response, dict):
            choices = response.get("choices") or []
            if not choices:
                raise ModelError("chat response has no choices")
            first = choices[0]
            message = first.get("message", {}) if isinstance(first, dict) else {}
        else:
            message = response.choices[0].message
        content = message.get("content") if isinstance(message, dict) else getattr(message, "content", None)
        if isinstance(content, list):
            parts = []
            for item in content:
                if isinstance(item, dict):
                    parts.append(str(item.get("text") or item.get("content") or ""))
                else:
                    parts.append(str(item))
            return "".join(parts)
        return str(content or "")

    @staticmethod
    def _retry_wait_seconds(cfg: dict[str, Any], attempt: int) -> float:
        minimum = float(cfg.get("retry_min_wait_sec", 2))
        maximum = float(cfg.get("retry_max_wait_sec", minimum))
        return min(maximum, minimum * (2 ** max(0, attempt - 1)))

    @staticmethod
    def _normalize(row: list[float]) -> list[float]:
        norm = sum(v * v for v in row) ** 0.5
        if norm == 0:
            return row
        return [v / norm for v in row]
