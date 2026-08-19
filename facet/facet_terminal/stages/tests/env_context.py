from __future__ import annotations

import csv
import json
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from common.io import read_json, write_json

from facet_terminal.pipeline import candidate_dir, task_root


SELECTED_FIXTURE_SUMMARIES_REL = "pipeline_artifacts/share/selected_fixture_summaries.json"

TEXT_SUFFIXES = {
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
    ".svg",
    ".srt",
    ".vtt",
}


class HeadingParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._capture: str | None = None
        self.title = ""
        self.headings: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() in {"title", "h1", "h2"}:
            self._capture = tag.lower()

    def handle_endtag(self, tag: str) -> None:
        if self._capture == tag.lower():
            self._capture = None

    def handle_data(self, data: str) -> None:
        text = " ".join(data.split())
        if not text or self._capture is None:
            return
        if self._capture == "title" and not self.title:
            self.title = text[:160]
        elif self._capture in {"h1", "h2"} and len(self.headings) < 12:
            self.headings.append(text[:160])


def load_real_env_file_summary(task_dir: Path) -> dict[str, Any]:
    path = task_dir / "pipeline_artifacts" / "share" / "real_env_file_summary.json"
    if path.exists():
        payload = read_json(path)
        if isinstance(payload, dict):
            return payload
    return {"summary_type": "real_env_file_summary", "task_files": [], "task_directories": []}


def is_text_fixture(path: str) -> bool:
    return Path(path).suffix.lower() in TEXT_SUFFIXES or Path(path).name.lower() in {"readme", "makefile", "license"}


def compact_text(text: str, limit: int) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    if len(text) <= limit:
        return text
    head = text[: limit // 2].rstrip()
    tail = text[-limit // 2 :].lstrip()
    return f"{head}\n\n...[truncated]...\n\n{tail}"


def sample_item_keys(items: list[Any]) -> list[str]:
    for item in items:
        if isinstance(item, dict):
            return list(item.keys())[:24]
    return []


def summarize_json(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        keys = list(value.keys())
        summary: dict[str, Any] = {"type": "object", "top_level_keys": keys[:30], "key_count": len(keys)}
        nested = []
        for key, item in value.items():
            if isinstance(item, list):
                nested.append({"key": key, "type": "array", "count": len(item), "sample_item_keys": sample_item_keys(item)})
            elif isinstance(item, dict):
                nested.append({"key": key, "type": "object", "keys": list(item.keys())[:20]})
            if len(nested) >= 8:
                break
        summary["nested_shapes"] = nested
        return summary
    if isinstance(value, list):
        return {"type": "array", "count": len(value), "sample_item_keys": sample_item_keys(value)}
    return {"type": type(value).__name__}


def summarize_csv(text: str, delimiter: str = ",") -> dict[str, Any]:
    rows = list(csv.reader(text.splitlines()[:50], delimiter=delimiter))
    header = rows[0] if rows else []
    return {"type": "csv" if delimiter == "," else "tsv", "columns": header[:40], "sample_row_count": max(0, len(rows) - 1)}


def summarize_markdown(text: str) -> dict[str, Any]:
    headings = [line.strip("# ").strip() for line in text.splitlines() if line.lstrip().startswith("#")]
    return {"type": "markdown", "headings": headings[:20], "line_count": len(text.splitlines())}


def summarize_html(text: str) -> dict[str, Any]:
    parser = HeadingParser()
    try:
        parser.feed(text)
    except Exception:
        pass
    return {"type": "html", "title": parser.title, "headings": parser.headings}


def summarize_text_file(path: str, text: str) -> dict[str, Any]:
    suffix = Path(path).suffix.lower()
    if suffix == ".json":
        try:
            return summarize_json(json.loads(text))
        except json.JSONDecodeError as exc:
            return {"type": "json", "parse_error": str(exc)}
    if suffix == ".jsonl":
        lines = [line for line in text.splitlines() if line.strip()]
        samples = []
        for line in lines[:5]:
            try:
                samples.append(summarize_json(json.loads(line)))
            except json.JSONDecodeError:
                samples.append({"type": "jsonl_record", "parse_error": True})
        return {"type": "jsonl", "record_count_in_sample": len(lines), "sample_shapes": samples}
    if suffix == ".csv":
        return summarize_csv(text, ",")
    if suffix == ".tsv":
        return summarize_csv(text, "\t")
    if suffix in {".md", ".markdown"}:
        return summarize_markdown(text)
    if suffix in {".html", ".htm"}:
        return summarize_html(text)
    return {"type": "text", "line_count": len(text.splitlines())}


def selected_fixture_summaries(task_dir: Path, real_summary: dict[str, Any], *, max_files: int = 24, max_bytes: int = 12000, max_total_chars: int = 70000) -> list[dict[str, Any]]:
    env_root = task_dir / "environment" / "task_file"
    results: list[dict[str, Any]] = []
    total_chars = 0
    for item in list(real_summary.get("task_files") or [])[:max_files]:
        rel_path = str(item.get("path") or "").strip("/")
        if not rel_path or Path(rel_path).name == ".gitkeep":
            continue
        entry: dict[str, Any] = {
            "path": item.get("absolute_path") or f"/task_file/{rel_path}",
            "relative_path": rel_path,
            "kind": item.get("kind") or Path(rel_path).suffix.lower().lstrip(".") or "file",
            "size_bytes": item.get("size_bytes"),
            "source_strategy": item.get("source_strategy"),
        }
        local_path = env_root / rel_path
        if local_path.exists() and local_path.is_file() and is_text_fixture(rel_path):
            raw = local_path.read_bytes()
            text = raw[: max_bytes + 1].decode("utf-8", errors="replace")
            entry["structure_summary"] = summarize_text_file(rel_path, text)
            remaining = max_total_chars - total_chars
            if remaining > 0:
                preview = compact_text(text, min(max_bytes, remaining))
                entry["content_preview"] = preview
                entry["content_truncated"] = len(raw) > len(preview.encode("utf-8", errors="replace"))
                total_chars += len(preview)
        else:
            entry["structure_summary"] = {"type": "non_text_or_missing_local_copy"}
        results.append(entry)
    return results


def load_or_build_selected_fixture_summaries(task_dir: Path, cfg: dict[str, Any], real_summary: dict[str, Any], *, prefix: str = "") -> list[dict[str, Any]]:
    summaries = selected_fixture_summaries(
        task_dir,
        real_summary,
        max_files=int(cfg.get(f"{prefix}fixture_summary_max_files", cfg.get("fixture_summary_max_files", 24))),
        max_bytes=int(cfg.get(f"{prefix}fixture_summary_max_bytes", cfg.get("fixture_summary_max_bytes", 12000))),
        max_total_chars=int(cfg.get(f"{prefix}fixture_summary_max_total_chars", cfg.get("fixture_summary_max_total_chars", 70000))),
    )
    path = task_dir / SELECTED_FIXTURE_SUMMARIES_REL
    write_json(path, summaries)
    return summaries


def read_instruction_md(task_dir: Path, unit: dict[str, Any]) -> str:
    path = task_dir / "instruction.md"
    if path.exists():
        return path.read_text(encoding="utf-8", errors="replace").strip()
    instruction = unit.get("instruction")
    if isinstance(instruction, dict):
        return str(instruction.get("instruction_md") or "").strip()
    return ""


def read_generated_dockerfile(task_dir: Path) -> dict[str, Any]:
    path = task_dir / "environment" / "Dockerfile"
    if not path.exists():
        return {"path": "environment/Dockerfile", "exists": False, "content": ""}
    return {
        "path": "environment/Dockerfile",
        "exists": True,
        "content": path.read_text(encoding="utf-8", errors="replace"),
    }


def capture_environment_state(ctx: Any, cfg: dict[str, Any], unit: dict[str, Any]) -> dict[str, Any]:
    task_id = str(unit["task_id"])
    task_dir = candidate_dir(ctx, task_id)
    root = task_root(cfg)
    instruction_md = read_instruction_md(task_dir, unit)
    real_summary = load_real_env_file_summary(task_dir)
    fixture_summaries = load_or_build_selected_fixture_summaries(task_dir, cfg, real_summary)
    directories = list(real_summary.get("task_directories") or [])
    file_parent_dirs = {str(Path(str(path).replace(root.rstrip("/") + "/", "")).parent) for path in real_summary.get("task_file_paths") or []}
    empty_dirs = []
    for item in directories:
        rel = str(item.get("path") or ".")
        if rel not in file_parent_dirs:
            empty_dirs.append(item.get("absolute_path") or f"{root}/{rel}".rstrip("/"))
    return {
        "capture_method": "environment_state_with_generated_solution_context",
        "task_root": root,
        "instruction_md": instruction_md,
        "real_env_file_summary": real_summary,
        "selected_fixture_summaries": fixture_summaries,
        "environment_metadata": {
            "visible_file_count": len(real_summary.get("task_files") or []),
            "visible_directory_count": len(real_summary.get("task_directories") or []),
            "empty_directories": sorted(set(str(item) for item in empty_dirs if item)),
            "maturity": real_summary.get("maturity", {}),
            "validation": real_summary.get("validation", {}),
        },
    }
