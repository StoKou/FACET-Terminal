"""Adapters from external JSONL records to FACET-Terminal's canonical skill-pair schema."""
from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any


class InputAdapterError(ValueError):
    """Raised when an input record cannot be adapted to a skill pair."""


def _string_list(value: Any, field: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, (list, tuple)):
        raise InputAdapterError(f"{field} must be a list")
    return [str(item).strip() for item in value if str(item).strip()]


def _canonicalize(payload: Mapping[str, Any]) -> dict[str, Any]:
    skill_ids = _string_list(payload.get("skill_ids"), "skill_ids")
    summaries = _string_list(payload.get("skill_summaries"), "skill_summaries")
    scenarios = _string_list(payload.get("scenario_texts"), "scenario_texts")
    if len(skill_ids) != 2:
        raise InputAdapterError(f"skill pair must contain exactly two skill_ids; got {len(skill_ids)}")
    if summaries and len(summaries) != 2:
        raise InputAdapterError(
            f"skill pair must contain exactly two skill_summaries when provided; got {len(summaries)}"
        )
    quality = payload.get("quality", {})
    return {
        "pair_id": str(payload.get("pair_id") or "").strip(),
        "skill_ids": skill_ids,
        "skill_summaries": summaries,
        "scenario_texts": scenarios,
        "quality": dict(quality) if isinstance(quality, Mapping) else {},
    }


def adapt_skill_pair(record: Mapping[str, Any], _: Mapping[str, Any]) -> dict[str, Any]:
    """Adapt the native flat skill-pair record."""
    return _canonicalize(record)


def adapt_skill_objects(record: Mapping[str, Any], source: Mapping[str, Any]) -> dict[str, Any]:
    """Adapt a record whose two skills are represented as objects."""
    skills_field = str(source.get("skills_field", "skills"))
    skill_id_field = str(source.get("skill_id_field", "id"))
    summary_field = str(source.get("skill_summary_field", "summary"))
    skills = record.get(skills_field)
    if not isinstance(skills, list):
        raise InputAdapterError(f"{skills_field} must be a list")
    if any(not isinstance(skill, Mapping) for skill in skills):
        raise InputAdapterError(f"each item in {skills_field} must be an object")
    return _canonicalize(
        {
            "pair_id": record.get("pair_id"),
            "skill_ids": [skill.get(skill_id_field) for skill in skills],
            "skill_summaries": [skill.get(summary_field) for skill in skills if skill.get(summary_field)],
            "scenario_texts": record.get("scenario_texts", record.get("scenarios", [])),
            "quality": record.get("quality", {}),
        }
    )


def _get_nested(record: Mapping[str, Any], path: str) -> Any:
    value: Any = record
    for part in path.split("."):
        if not isinstance(value, Mapping) or part not in value:
            return None
        value = value[part]
    return value


def adapt_mapped(record: Mapping[str, Any], source: Mapping[str, Any]) -> dict[str, Any]:
    """Adapt arbitrary object layouts with a dotted-path field map."""
    field_map = source.get("field_map")
    if not isinstance(field_map, Mapping) or "skill_ids" not in field_map:
        raise InputAdapterError("mapped_jsonl requires field_map.skill_ids")
    payload = {
        field: _get_nested(record, str(path))
        for field, path in field_map.items()
        if field in {"pair_id", "skill_ids", "skill_summaries", "scenario_texts", "quality"}
    }
    return _canonicalize(payload)


Adapter = Callable[[Mapping[str, Any], Mapping[str, Any]], dict[str, Any]]
ADAPTERS: dict[str, Adapter] = {
    "skill_pair_jsonl": adapt_skill_pair,
    "skill_objects_jsonl": adapt_skill_objects,
    "mapped_jsonl": adapt_mapped,
}


def adapt_record(record: Mapping[str, Any], source: Mapping[str, Any]) -> dict[str, Any]:
    """Dispatch one external record through its configured adapter."""
    format_name = str(source.get("format", "skill_pair_jsonl"))
    adapter = ADAPTERS.get(format_name)
    if adapter is None:
        supported = ", ".join(sorted(ADAPTERS))
        raise InputAdapterError(f"unsupported input format {format_name!r}; supported formats: {supported}")
    return adapter(record, source)
