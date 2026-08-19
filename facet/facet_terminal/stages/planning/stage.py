from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import shutil
import time
from typing import Any

from common.context import RunContext, utc_now
from common.hashing import file_hash
from common.io import append_jsonl, read_jsonl, write_jsonl, write_text
from common.progress import ProgressBar
from common.model_pool import ModelClient

from facet_terminal.pipeline import (
    ArtifactWriter,
    candidate_dir,
    record_event,
    stage_cfg,
    stage_log_dir,
    task_root,
    worker_count,
    write_stage_report,
)
from facet_terminal.prompts import PLANNING_USER_PROMPT, PROMPT_VERSION, render_prompt


def _profile_for_unit(profiles: list[str], key: str) -> str | None:
    if not profiles:
        return None
    from common.hashing import short_hash

    return profiles[int(short_hash(key, 8), 16) % len(profiles)]


def template_plan(ctx: RunContext, cfg: dict[str, Any], unit: dict[str, Any]) -> dict[str, Any]:
    scenario_texts = [str(item) for item in unit.get("scenario_texts", [])]
    skill_summaries = [str(item) for item in unit.get("skill_summaries", [])]
    return {
        "task_theme": "Local terminal workflow synthesized from a related skill pair.",
        "solution_workflow": "Use both skill summaries and the scenario descriptions as source material, preserve the intent of both skills in one local terminal workflow, and produce a final structured artifact that records their integrated roles, inferred inputs, and inferred outputs.",
        "scenario_integration_map": [
            {
                "scenario_index": index + 1,
                "role_in_solution": scenario_texts[index] if index < len(scenario_texts) else "Scenario state integrated into the workflow narrative.",
            }
            for index in range(len(scenario_texts))
        ],
        "skill_integration_map": [
            {
                "skill_index": index + 1,
                "role_in_solution": skill_summaries[index] if index < len(skill_summaries) else "Skill capability integrated into the workflow narrative.",
            }
            for index in range(len(skill_summaries))
        ],
        "key_inputs": ["skill-pair scenario descriptions", "two skill summaries", "pair metadata"],
        "key_outputs": ["workflow summary artifact", "scenario and skill integration report"],
    }


def validate_plan(plan: dict[str, Any], unit: dict[str, Any], root: str) -> dict[str, Any]:
    for key in ("task_theme", "solution_workflow"):
        if not str(plan.get(key, "")).strip():
            raise ValueError(f"planning_reference_missing_{key}")
    for key in ("scenario_integration_map", "skill_integration_map", "key_inputs", "key_outputs"):
        if not isinstance(plan.get(key), list):
            raise ValueError(f"planning_reference_missing_{key}")
    scenario_texts = [str(item) for item in unit.get("scenario_texts", [])]
    skill_summaries = [str(item) for item in unit.get("skill_summaries", [])]
    expected_scenarios = list(range(1, len(scenario_texts) + 1))
    expected_skills = list(range(1, len(skill_summaries) + 1))
    scenario_map = [item for item in plan["scenario_integration_map"] if isinstance(item, dict)]
    skill_map = [item for item in plan["skill_integration_map"] if isinstance(item, dict)]
    scenario_roles_by_index = {}
    for index, item in enumerate(scenario_map, start=1):
        raw_index = item.get("scenario_index", index)
        try:
            scenario_index = int(raw_index)
        except (TypeError, ValueError):
            scenario_index = index
        scenario_roles_by_index[scenario_index] = str(item.get("role_in_solution", "")).strip()
    skill_roles_by_index = {}
    for index, item in enumerate(skill_map, start=1):
        raw_index = item.get("skill_index", index)
        try:
            skill_index = int(raw_index)
        except (TypeError, ValueError):
            skill_index = index
        skill_roles_by_index[skill_index] = str(item.get("role_in_solution", "")).strip()
    warnings = []
    if sorted(scenario_roles_by_index) != expected_scenarios:
        warnings.append("scenario_integration_map_normalized_to_input_order")
    if sorted(skill_roles_by_index) != expected_skills:
        warnings.append("skill_integration_map_normalized_to_input_order")
    plan["scenario_integration_map"] = [
        {
            "scenario_index": scenario_index,
            "role_in_solution": scenario_roles_by_index.get(scenario_index)
            or (str(scenario_map[index].get("role_in_solution", "")).strip() if index < len(scenario_map) else "")
            or (scenario_texts[index] if index < len(scenario_texts) else "Scenario integrated into the unified solution workflow."),
        }
        for index, scenario_index in enumerate(expected_scenarios)
    ]
    plan["skill_integration_map"] = [
        {
            "skill_index": skill_index,
            "role_in_solution": skill_roles_by_index.get(skill_index)
            or (str(skill_map[index].get("role_in_solution", "")).strip() if index < len(skill_map) else "")
            or (skill_summaries[index] if index < len(skill_summaries) else "Skill integrated into the unified solution workflow."),
        }
        for index, skill_index in enumerate(expected_skills)
    ]
    plan["key_inputs"] = [str(item).strip() for item in plan["key_inputs"] if str(item).strip()]
    plan["key_outputs"] = [str(item).strip() for item in plan["key_outputs"] if str(item).strip()]
    if not plan["key_inputs"]:
        plan["key_inputs"] = ["local input files inferred from the scenario-skill workflow"]
    if not plan["key_outputs"]:
        plan["key_outputs"] = ["final artifacts inferred from the scenario-skill workflow"]
    return plan


def plan_one(ctx: RunContext, cfg: dict[str, Any], model_client: Any, unit: dict[str, Any]) -> dict[str, Any]:
    task_id = str(unit["task_id"])
    started = time.monotonic()
    checkpoint_path = ctx.path(str(cfg.get("checkpoint_jsonl", "checkpoints/facet_terminal_planning/checkpoint.jsonl")))
    log_dir = stage_log_dir(ctx, "planning", task_id)
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        obsolete_dir = candidate_dir(ctx, task_id) / "pipeline_artifacts" / "planning"
        if obsolete_dir.exists():
            shutil.rmtree(obsolete_dir)
        mode = str(cfg.get("mode", "template"))
        root = task_root(cfg)
        if mode == "template":
            plan = template_plan(ctx, cfg, unit)
            call_id = None
            profile = None
        else:
            if model_client is None:
                raise ValueError("model_client_required_for_llm_planning")
            context = {
                "scenario_texts": [
                    {"scenario_index": index, "text": str(text)}
                    for index, text in enumerate(unit.get("scenario_texts", []), start=1)
                ],
                "skill_summaries": [
                    {"skill_index": index, "summary": str(summary)}
                    for index, summary in enumerate(unit.get("skill_summaries", []), start=1)
                ],
            }
            user_prompt = render_prompt(PLANNING_USER_PROMPT, context, task_root=root, base_image="")
            write_text(log_dir / "prompt.txt", user_prompt)
            profile = _profile_for_unit([str(item) for item in cfg.get("model_profiles", [])], str(unit.get("pair_id", task_id)))
            plan, call_id = model_client.chat_json("facet_terminal_planning", str(unit.get("pair_id", task_id)), "", user_prompt, profile)
            writer_tmp = ArtifactWriter(ctx, "planning")
            writer_tmp.write_json(task_id, "pipeline_artifacts/planning/model_payload.json", plan)
        plan = validate_plan(plan, unit, root)
        writer = ArtifactWriter(ctx, "planning")
        writer.write_json(task_id, "pipeline_artifacts/planning/planning_reference.json", plan)
        writer.write_json(task_id, "pipeline_artifacts/planning/model_payload.json", plan)
        row = dict(unit)
        row["planning_reference"] = plan
        row["task_plan"] = {"planning_reference": plan, "tags": list(unit.get("skill_summaries") or unit.get("skill_ids") or [])[:8]}
        row["planning"] = {"mode": mode, "prompt_version": PROMPT_VERSION, "model_profile": profile, "model_call_id": call_id, "latency_ms": int((time.monotonic() - started) * 1000)}
        result = {"status": "planned", "task_id": task_id, "planned_unit": row}
        record_event(ctx, task_id, "planning", "plan_ready")
    except Exception as exc:
        result = {"status": "failed", "task_id": task_id, "reason": "planning_exception", "error": repr(exc)}
        write_text(log_dir / "planning_exception.json", json.dumps(result, ensure_ascii=False, indent=2) + "\n")
        record_event(ctx, task_id, "planning", "planning_failed", error=repr(exc))
    append_jsonl(checkpoint_path, result)
    return result


def run(ctx: RunContext, args: argparse.Namespace) -> None:
    stage = "planning"
    started = utc_now()
    cfg = stage_cfg(ctx, stage)
    input_path = ctx.path(str(cfg.get("input_jsonl", "artifacts/facet_terminal/selected_units.jsonl")))
    output_path = ctx.path(str(cfg.get("output_jsonl", "artifacts/facet_terminal/planned_units.jsonl")))
    checkpoint_path = ctx.path(str(cfg.get("checkpoint_jsonl", "checkpoints/facet_terminal_planning/checkpoint.jsonl")))
    units = read_jsonl(input_path)
    if args.limit:
        units = units[: args.limit]
    completed = {}
    if args.resume:
        for row in read_jsonl(checkpoint_path):
            if row.get("status") == "planned":
                completed[str(row.get("task_id"))] = row
    pending = [unit for unit in units if str(unit.get("task_id")) not in completed]
    workers = worker_count(ctx, stage, cfg, args.workers)
    model_client = ModelClient(ctx) if str(cfg.get("mode", "template")) != "template" else None
    results = list(completed.values())
    with ProgressBar("facet_terminal_planning:planning", len(pending)) as progress:
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="facet-terminal-planning") as executor:
            futures = {executor.submit(plan_one, ctx, cfg, model_client, unit): unit for unit in pending}
            for future in as_completed(futures):
                unit = futures[future]
                results.append(future.result())
                progress.update(suffix=str(unit.get("task_id", "")))
    planned = [row["planned_unit"] for row in results if row.get("status") == "planned"]
    planned.sort(key=lambda item: int(item.get("selected_index", 0) or 0))
    write_jsonl(output_path, planned)
    summary = {"input_count": len(units), "planned_count": len(planned), "failed_count": len(results) - len(planned)}
    write_stage_report(
        ctx,
        stage,
        started,
        {"selected_units": {"path": str(input_path.relative_to(ctx.run_dir)), "hash": file_hash(input_path)}},
        {"planned_units": {"path": str(output_path.relative_to(ctx.run_dir)), "records": len(planned), "hash": file_hash(output_path)}},
        summary,
        cfg,
    )
