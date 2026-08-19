from __future__ import annotations

import argparse
from pathlib import Path

from common.context import RunContext, utc_now
from common.hashing import file_hash
from common.io import read_jsonl, write_json, write_jsonl, write_text
from common.model_pool import ModelClient

from facet_terminal.pipeline import ArtifactWriter, base_image, candidate_dir, record_event, safe_rel_path, stage_cfg, stage_log_dir, stage_report_dir, task_root, worker_count, write_stage_report
from facet_terminal.prompts import PROMPT_VERSION, SOLUTION_USER_PROMPT, render_prompt
from facet_terminal.scheduler import run_batched
from facet_terminal.stages.tests.env_context import load_or_build_selected_fixture_summaries, load_real_env_file_summary, read_generated_dockerfile, read_instruction_md


def solve_script(root: str) -> str:
    return f"""#!/bin/bash
set -e
cd {root}
python3 - <<'PY'
import json
from pathlib import Path
root = Path({root!r})
metadata = json.loads((root / "input" / "metadata.json").read_text())
scenarios = [s for s in (root / "input" / "scenarios.txt").read_text().split("\\n---\\n") if s.strip()]
payload = {{
    "pair_id": metadata["pair_id"],
    "scenario_count": len(scenarios),
    "skill_ids": metadata["skill_ids"],
    "first_scenario_preview": scenarios[0][:160] if scenarios else "",
    "last_scenario_preview": scenarios[-1][:160] if scenarios else "",
}}
(root / "output").mkdir(exist_ok=True)
(root / "output" / "summary.json").write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\\n")
PY
"""


def partial_missing_skill_ids(root: str) -> str:
    return f"""#!/bin/bash
set -e
cd {root}
python3 - <<'PY'
import json
from pathlib import Path
root = Path({root!r})
metadata = json.loads((root / "input" / "metadata.json").read_text())
scenarios = [s for s in (root / "input" / "scenarios.txt").read_text().split("\\n---\\n") if s.strip()]
(root / "output").mkdir(exist_ok=True)
(root / "output" / "summary.json").write_text(json.dumps({{"pair_id": metadata["pair_id"], "scenario_count": len(scenarios)}}) + "\\n")
PY
"""


def partial_wrong_count(root: str) -> str:
    return f"""#!/bin/bash
set -e
cd {root}
python3 - <<'PY'
import json
from pathlib import Path
root = Path({root!r})
metadata = json.loads((root / "input" / "metadata.json").read_text())
(root / "output").mkdir(exist_ok=True)
(root / "output" / "summary.json").write_text(json.dumps({{"pair_id": metadata["pair_id"], "scenario_count": -1, "skill_ids": metadata["skill_ids"]}}) + "\\n")
PY
"""


def _profile_for_unit(profiles: list[str], key: str) -> str | None:
    if not profiles:
        return None
    from common.hashing import short_hash

    return profiles[int(short_hash(key, 8), 16) % len(profiles)]


def template_solution_payload(unit: dict, root: str) -> dict:
    return {
        "solution_sh": solve_script(root),
        "partials": [
            {"name": "partial_solve_missing_skill_ids.sh", "content": partial_missing_skill_ids(root)},
            {"name": "partial_solve_wrong_count.sh", "content": partial_wrong_count(root)},
        ],
    }


def _solution_context(ctx: RunContext, cfg: dict, unit: dict) -> dict:
    task_id = str(unit["task_id"])
    task = candidate_dir(ctx, task_id)
    root = task_root(cfg)
    real_summary = load_real_env_file_summary(task)
    fixture_summaries = load_or_build_selected_fixture_summaries(task, cfg, real_summary, prefix="solution_")
    return {
        "task_id": task_id,
        "instruction_md": read_instruction_md(task, unit),
        "real_env_file_summary": {
            "summary_type": real_summary.get("summary_type"),
            "task_root": real_summary.get("task_root", root),
            "counts": real_summary.get("counts", {}),
            "task_file_paths": real_summary.get("task_file_paths", []),
            "task_directory_paths": real_summary.get("task_directory_paths", []),
            "task_files": real_summary.get("task_files", []),
            "task_directories": real_summary.get("task_directories", []),
        },
        "selected_fixture_summaries": fixture_summaries,
        "environment_metadata": {
            "visible_file_count": len(real_summary.get("task_files") or []),
            "visible_directory_count": len(real_summary.get("task_directories") or []),
            "maturity": real_summary.get("maturity", {}),
            "validation": real_summary.get("validation", {}),
        },
        "generated_dockerfile": read_generated_dockerfile(task),
        "constraints": {
            "task_root": root,
            "base_image": base_image(ctx, cfg),
            "prompt_version": PROMPT_VERSION,
        },
    }


def solution_payload_from_model(ctx: RunContext, cfg: dict, model_client: ModelClient, unit: dict) -> tuple[dict, str | None, str | None]:
    task_id = str(unit["task_id"])
    root = task_root(cfg)
    context = _solution_context(ctx, cfg, unit)
    prompt = render_prompt(SOLUTION_USER_PROMPT, context, task_root=root, base_image=base_image(ctx, cfg))
    log_dir = stage_log_dir(ctx, "solution", task_id)
    write_text(log_dir / "prompt.txt", prompt)
    profile = _profile_for_unit([str(item) for item in cfg.get("model_profiles", [])], str(unit.get("pair_id", task_id)))
    payload, call_id = model_client.chat_json("facet_terminal_solution", str(unit.get("pair_id", task_id)), "", prompt, profile)
    write_json(log_dir / "model_payload.json", payload)
    return payload, profile, call_id


def normalize_script(source: str, root: str) -> str:
    text = str(source or "").replace("\r\n", "\n").strip()
    if not text.startswith("#!"):
        text = "#!/bin/bash\nset -e\n" + text
    lines = text.splitlines()
    if not any(line.strip().startswith("set -e") for line in lines[:6]):
        lines.insert(1, "set -e")
    if not any(line.strip() == f"cd {root}" for line in lines[:10]):
        lines.insert(2, f"cd {root}")
    return "\n".join(lines).rstrip() + "\n"


def write_solution_payload(ctx: RunContext, cfg: dict, unit: dict, payload: dict) -> list[str]:
    task_id = str(unit["task_id"])
    root = task_root(cfg)
    writer = ArtifactWriter(ctx, "solution")
    solution = payload.get("solution_sh")
    if not isinstance(solution, str) or not solution.strip():
        raise ValueError("solution_sh_missing")
    writer.write_text(task_id, "solution/solve.sh", normalize_script(solution, root), executable=True)
    written = ["solution/solve.sh"]
    partials = payload.get("partials")
    if not isinstance(partials, list) or not partials:
        partials = []
    for index, partial in enumerate(partials[:3], start=1):
        if not isinstance(partial, dict):
            continue
        name = str(partial.get("name") or f"partial_solve_{index}.sh")
        if not safe_rel_path(name) or "/" in name or not name.endswith(".sh"):
            name = f"partial_solve_{index}.sh"
        writer.write_text(task_id, f"solution/{name}", normalize_script(str(partial.get("content", "")), root), executable=True)
        written.append(f"solution/{name}")
    if len(written) == 1:
        writer.write_text(task_id, "solution/partial_solve_1.sh", "#!/bin/bash\nset -e\n" + f"cd {root}\nmkdir -p output\n", executable=True)
        written.append("solution/partial_solve_1.sh")
    return written


def solution_one(ctx: RunContext, cfg: dict, model_client: ModelClient | None, unit: dict) -> dict:
    task_id = str(unit["task_id"])
    root = task_root(cfg)
    try:
        mode = str(cfg.get("mode", "llm"))
        if mode == "template":
            payload = template_solution_payload(unit, root)
            profile = None
            call_id = None
        else:
            if model_client is None:
                raise ValueError("model_client_required_for_llm_solution")
            payload, profile, call_id = solution_payload_from_model(ctx, cfg, model_client, unit)
        written = write_solution_payload(ctx, cfg, unit, payload)
        report = {"task_id": task_id, "status": "solution_ready", "mode": mode, "model_profile": profile, "model_call_id": call_id, "dry_run_checked": False, "written": written}
        write_json(stage_report_dir(ctx, "solution") / f"{task_id}.json", report)
        record_event(ctx, task_id, "solution", "solution_ready")
        row = dict(unit)
        row["solution"] = report
        return {"status": "solution_ready", "task_id": task_id, "unit": row}
    except Exception as exc:
        report = {"task_id": task_id, "status": "solution_failed", "error": repr(exc)}
        write_json(stage_report_dir(ctx, "solution") / f"{task_id}.json", report)
        record_event(ctx, task_id, "solution", "solution_failed", error=repr(exc))
        return {"status": "solution_failed", "task_id": task_id, "unit": unit}


def run(ctx: RunContext, args: argparse.Namespace) -> None:
    stage = "solution"
    started = utc_now()
    cfg = stage_cfg(ctx, stage)
    input_path = ctx.path(str(cfg.get("input_jsonl", "artifacts/facet_terminal/instruction_units.jsonl")))
    output_path = ctx.path(str(cfg.get("output_jsonl", "artifacts/facet_terminal/solution_units.jsonl")))
    units = read_jsonl(input_path)
    if args.limit:
        units = units[: args.limit]
    model_client = ModelClient(ctx) if str(cfg.get("mode", "llm")) != "template" else None
    results = run_batched("facet_terminal_solution:write", units, worker_count(ctx, stage, cfg, args.workers), int(cfg.get("batch_size", 8)), int(cfg.get("max_inflight_batches", 2)), lambda unit: solution_one(ctx, cfg, model_client, unit))
    ready = [row["unit"] for row in results if row.get("status") == "solution_ready"]
    write_jsonl(output_path, ready)
    write_stage_report(ctx, stage, started, {"instruction_units": {"path": str(input_path.relative_to(ctx.run_dir)), "hash": file_hash(input_path)}}, {"solution_units": {"path": str(output_path.relative_to(ctx.run_dir)), "records": len(ready), "hash": file_hash(output_path)}}, {"input_count": len(units), "solution_ready": len(ready), "solution_failed": len(results) - len(ready)}, cfg)
