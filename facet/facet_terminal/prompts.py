from __future__ import annotations

import json
from typing import Any


PROMPT_VERSION = "facet_terminal_env_instruction_ref_prompts_011"


PLANNING_USER_PROMPT = """You are a Skill-Pair Solution Synthesizer for terminal-task construction.

Your task is to reconstruct ONE coherent natural-language reference solution workflow from a related pair of skills.

IMPORTANT:
You MUST use ALL scenario_texts and ALL skill_summaries.
Nothing is allowed to be ignored or discarded.
If some elements seem unrelated, you must still integrate them into the same coherent workflow by interpreting their role (e.g., preprocessing, validation, side-effect, auxiliary step, or fallback mechanism).

---

# INPUT
You will receive:
- scenario_texts: ordered numbered nodes, each with scenario_index and text
- skill_summaries: ordered numbered edges, each with skill_index and summary

The two skills and their scenario descriptions form one compositional task source. Every provided element is meaningful.

---

# CORE PRINCIPLE

You must construct ONE unified solution narrative that explains:
- how all scenarios connect into a single workflow
- how all skills contribute at different stages or layers
- how intermediate states evolve into final outputs
- how verification or side-effects fit into the process

You are NOT allowed to drop, ignore, or mark anything as irrelevant.

Instead:
- reinterpret every element into a role in the workflow
- even if weakly related, assign it a supporting function

---

# OUTPUT REQUIREMENTS

Return ONLY JSON:

{
  "task_theme": "single coherent synthesis of the full path",

  "solution_workflow": "a detailed natural-language explanation of a complete solution process. MUST incorporate every scenario and skill into the workflow, explaining their role in a unified system. No commands or code.",

  "scenario_integration_map": [
    {
      "scenario_index": 1,
      "role_in_solution": "how this scenario is used in the workflow"
    }
  ],

  "skill_integration_map": [
    {
      "skill_index": 1,
      "role_in_solution": "how this skill contributes to the workflow"
    }
  ],

  "key_inputs": [
    "inferred inputs from full graph"
  ],

  "key_outputs": [
    "final artifacts or results"
  ]
}

---

# RULES

- MUST include ALL scenarios and skills
- Use scenario_index and skill_index only; do NOT return source ids, edge ids, or path ids
- MUST NOT drop or ignore any element
- MUST NOT generate code or commands
- MUST NOT assume external APIs or infrastructure
- MUST build a single coherent narrative, not multiple competing workflows
- solution_workflow must be natural language paragraphs

INPUT JSON:
{INPUT_JSON}
"""


ENV_USER_PROMPT = """Generate the initial Dockerfile and build-context files for a FACET-Terminal task.

# ROLE

Build the starting environment from `instruction_ref`, `dockerfile_template`, and `constraints.base_image`.
Use `instruction_ref` as the source of truth for visible starting materials and required final outputs.
Ignore upstream planning fields unless their content is repeated in `instruction_ref`.
If `env_repair_hint` is present, this is a retry after a previous environment-generation failure; directly address that failure and do not repeat the same invalid file paths, direct non-simple fixtures, oversized inline files, or forbidden outputs.

---

# HARD BOUNDARY

Do not solve the task or create final deliverables.
Do not create tests, solution files, hidden validation files, benchmark internals, or task-answer files.
Do not create fake binaries, fake Python modules, package stubs, wrapper commands, or command replays.
Do not create static replay output or precomputed answer-like artifacts to satisfy checks.
Do not embed task execution, validation, or answer-generation logic in Dockerfile `RUN` layers.
Do not require private APIs, authenticated CLIs, real tokens, cookies, credentials, browser sessions, private repositories, or non-public datasets.
Network access may exist during Docker build, but the task environment must not depend on private services or volatile live state.
Redacted credentials may appear only as inert fixture text or metadata.

---

# ENVIRONMENT CONSTRUCTION

Return a complete Dockerfile based on `dockerfile_template`.
Preserve `FROM __BASE_IMAGE__`, keep `WORKDIR __TASK_ROOT__`, and copy visible starting files into `__TASK_ROOT__`.
Return `build_context_files` for realistic starting fixtures, empty output directories, and optional `build_scripts/` generators.
Return `env_checks` for environment readiness only.
Do not put smoke checks in Dockerfile `RUN` layers; keep `RUN test ...`, `RUN which ...`, `RUN command -v ...`, and JSON/CSV parsing checks in `env_checks`.
If a final output path is required, create only its parent directory, not the final file.
Keep Dockerfile `RUN` layers environment-focused: install public packages, configure locale/env vars, and execute deterministic fixture generators only when needed.
Prefer one combined apt installation layer using `apt-get update && apt-get install -y --no-install-recommends ... && rm -rf /var/lib/apt/lists/*`.
Use `ENV LANG=C.UTF-8 LC_ALL=C.UTF-8` when text fixtures or tools may handle non-ASCII content.
Do not use multi-stage builds, do not copy tests/solution/hidden paths, and do not set a task-solving `CMD` or `ENTRYPOINT`.

---

# FIXTURE REALISM

Generated starting files must look like realistic captured source artifacts, not simplified answer templates.
Do not generate fixtures that are already normalized into the required final output structure.
Starting files should be raw or semi-raw source snapshots. The final consolidation, filtering, and normalization must remain for the solver.

For each important JSON/log/CSV fixture:
- Include provider-style envelope fields such as request_id, captured_at, source, api_version, status_code, warnings, pagination, request_params, response_metadata, or trace_id when plausible.
- Include extra realistic fields that are not needed for the final answer.
- Include multiple records, not only the exact record needed by the task.
- Include at least one distractor, stale entry, degraded entry, disabled item, failed item, or lower-priority candidate when plausible.
- Preserve enough redundancy that the solver must select, filter, reconcile, or validate information rather than copy one field.
- Use stable IDs across files so records can be cross-referenced.
- Do not make input field names exactly mirror the final output schema unless that is natural for the source.
- Avoid tiny toy fixtures. Important JSON fixtures should usually contain nested objects, arrays, metadata, and 5-15 realistic fields per major record.
- Logs should include surrounding INFO/WARN/ERROR lines, timestamps, component names, and unrelated but plausible events.
- Manifests should describe fixture purpose and known quirks, but must not reveal the final answer.
- When a fixture is synthesized, generated, or publicly downloaded, record that source strategy in the fixture manifest using fields such as `source_strategy`, `generation_method`, and `reason`.

For flight-search-like snapshots, include request/provider metadata, currency, search window, warnings, 8-12 mixed candidates, direct and connecting itineraries, sold-out or expired fares, missing prices where plausible, detail URLs, segments, fare rules, lastTicketingTime, baggage, multiple connection airports, and at least one cheap but invalid distractor.
For agent-health-like snapshots, include summary, probe_config, checks, latency_ms, version, stderr_tail, disabled_reason, last_success_at, dependencies, and at least one unrelated or disabled agent entry when plausible.
For dry-run-like responses, include request_id, phase, requestPreview, validation, estimated_cost, policy_warnings, asset_probe, normalized_body, ignored_fields, and redacted sensitive headers.

---

# INLINE FILE AND PACKAGE RULES

Simple text fixtures may be returned directly in `build_context_files`, such as `.txt`, `.log`, `.csv`, `.json`, `.jsonl`, `.md`, `.yaml`, `.yml`, `.html`, `.xml`, small source files, and small config files.
Non-simple files must NOT be returned as direct `build_context_files` entries.
For non-simple files, use this priority order:
1. Public stable download during Docker build, only when a concrete public URL is available and the task does not depend on volatile live state.
2. Deterministic generation through files under `build_scripts/` using any suitable language or toolchain.
3. If a realistic binary/media/document fixture is unnecessary or too expensive, provide text-side metadata, transcript, manifest, or source snapshots instead.
Binary, database, archive, document, and media fixtures must be downloaded or generated during Docker build, not embedded as base64, fake text, or direct JSON string content.
For `.png`, `.jpg`, `.pdf`, `.docx`, `.pptx`, `.xlsx`, `.mp4`, `.webm`, `.mov`, `.mp3`, `.wav`, `.sqlite`, `.db`, `.zip`, `.tar`, and similar files: return generator/downloader files under `build_scripts/` plus Dockerfile `RUN` layers that execute them after `COPY build_scripts/ ...`.
Any public language/runtime is allowed for build generators, such as shell, Python, Node.js, Ruby, Perl, Go, Rust, Java, or small compiled C/C++ helpers, as long as the Dockerfile installs public required packages and the generation is deterministic.
If a realistic binary/media/document fixture is too expensive to generate, provide metadata, transcript, manifest, or source-side text fixtures instead of fake binary content.
Do not include generated or downloaded binary/media/document output paths as keys in `build_context_files`.
Generated or downloaded non-simple file paths may appear in fixture manifests, notes, and `env_checks`, but not as direct `build_context_files` entries.
Install only public, necessary Ubuntu packages in the Dockerfile.
Do not install private-service CLIs just because a domain name appears in the task.
Build scripts may generate starting fixtures but must not create final answers or install packages.
Prefer generated fixtures over huge inline JSON strings when content would be long; this keeps the model JSON valid and avoids truncation.

When retrying from `env_repair_hint`:
- For non-simple fixture failures, remove the direct file path and generate it from build scripts or public download steps, or replace it with realistic source metadata if the complex file is unnecessary.
- For forbidden path failures, move useful visible material out of tests/solution/hidden/validation paths into neutral input fixture paths.
- For final output failures, keep only the parent output directory.
- For JSONDecodeError-style failures, return fewer/lighter inline fixtures and move bulk generation into build scripts.

---

# OUTPUT SCHEMA

Return this JSON schema exactly:
{{
  "dockerfile": "complete Dockerfile text",
  "build_context_files": {{
    "task_file/input/file.txt": "content",
    "task_file/output/.gitkeep": "",
    "build_scripts/generate_fixtures.py": "",
    "build_scripts/generate_assets.sh": ""
  }},
  "env_checks": ["test -f __TASK_ROOT__/input/file.txt"],
  "notes": "short note about synthesized fixtures and package choices"
}}

INPUT JSON:
{input_json}
"""


ENV_REPAIR_USER_PROMPT = """Repair the Dockerfile and build-context files for a FACET-Terminal task.

This is a bounded environment repair. Fix only environment construction problems.

INPUT PROVIDED:
- instruction_ref: source of truth for the offline local task environment.
- dockerfile: previous Dockerfile text.
- build_context_files: previous build-context files.
- parsed_log: structured Docker build or smoke-check failure details.
- failure_type: policy/lint/build/launch/setup/model-output failure, such as dockerfile_lint_failed, build_failed, launch_failed, setup_failed, non_simple_fixture_must_be_generated_by_build_script, large_inline_fixture_must_be_generated_by_build_script, legacy binary_fixture_must_be_generated_by_build_script, forbidden_task_file_path, forbidden_build_context_path, final_output_file_not_allowed_in_env, or JSONDecodeError.
- constraints: task_root and base_image.

REPAIR SCOPE:
You may modify ONLY:
- dockerfile
- build_context_files
- delete_files
- env_checks

Do NOT create final deliverables.
Do NOT add fake binaries, fake modules, command replays, hidden tests, or solution logic.
Do NOT put smoke checks or validation-only commands in Dockerfile `RUN` layers.
Keep file existence checks, JSON/CSV parse checks, and `command -v` checks in `env_checks` only.
Prefer targeted fixes: missing Ubuntu packages, missing COPY source files, deterministic fixture generation fixes, permission fixes, or smoke-check corrections.
If the failure is a missing file, add a representative starting fixture to build_context_files and ensure the Dockerfile copies it.

FAILURE-SPECIFIC REPAIR POLICY:
- If failure_type contains `non_simple_fixture_must_be_generated_by_build_script`, `large_inline_fixture_must_be_generated_by_build_script`, or legacy `binary_fixture_must_be_generated_by_build_script`, delete the direct non-simple or oversized file entry and replace it with deterministic generator/downloader files under `build_scripts/` or a public download step in the Dockerfile. Any public language/runtime may be used if the Dockerfile installs it.
- The non-simple generated/downloaded path that failed must not remain as a `build_context_files` key. Keep it only in a fixture manifest and in `env_checks` such as `test -f __TASK_ROOT__/input/file.png`.
- If failure_type contains `forbidden_task_file_path` or `forbidden_build_context_path`, delete tests/solution/hidden/validation paths. If the content is useful as visible input, rename it into a neutral fixture path such as `task_file/input/tool_catalog/...`.
- If failure_type contains `final_output_file_not_allowed_in_env`, delete the final output file and keep only its parent directory with `.gitkeep`.
- If failure_type contains `JSONDecodeError`, avoid huge inline file contents. Return smaller fixture snapshots, split large fixtures into multiple files, or move generation into files under `build_scripts/`.
- If failure_type is `dockerfile_lint_failed`, fix only the offending Dockerfile instruction.
- If failure_type is `build_failed`, use parsed_log to add missing public packages, fix package names, remove unavailable version pins, add locale/CA certificates/build tools, or correct COPY/RUN ordering.
- If failure_type is `setup_failed`, correct `env_checks`, ensure generated fixtures are actually created during Docker build, or add missing visible starting fixtures. Do not create final outputs.
- If failure_type is `launch_failed`, keep the image launchable with a shell-friendly default; remove task-solving CMD/ENTRYPOINT unless it is purely environmental.

Return this JSON schema exactly:
{{
  "dockerfile": "complete repaired Dockerfile text",
  "build_context_files_patch": {{"task_file/input/file.txt": "content"}},
  "delete_files": [],
  "env_checks": ["test -d __TASK_ROOT__"],
  "repair_notes": "short explanation of the targeted repair"
}}

INPUT JSON:
{input_json}
"""


INSTRUCTION_REF_USER_PROMPT = """You are an expert system engineer and benchmark task designer.
Your goal is to synthesize an internal instruction reference for later environment construction.

INPUT PROVIDED:
- solution_workflow: the only planning field you may use. It is an internal natural-language reference workflow.
- constraints: task_root and prompt metadata.

CORE PRINCIPLE — CONVERT THE WORKFLOW INTO AN OFFLINE LOCAL TASK INTENT:

Use solution_workflow only to infer a locally solvable task objective, visible starting fixture files, and required final observable outputs.
Do not reveal the workflow itself. Do not describe steps, transformations, algorithms, commands, or implementation strategy.
This output is a reference for env_build, not the final instruction shown to the task-solving agent.

---

# EXTERNAL DEPENDENCY NORMALIZATION

solution_workflow may mention live APIs, authenticated CLIs, private services, blockchain wallets, publishing platforms, billing, cookies, flight search, ad platforms, real-time network calls, installed agent processes, or external URLs.

For instruction_ref, you MUST rewrite those runtime dependencies into local offline task materials.

Do NOT say the task requires:
- calling external APIs
- logging into services
- using real credentials, tokens, cookies, wallets, or API keys
- submitting real publishing requests
- querying live data
- initializing real blockchain or payment infrastructure
- checking real installed CLIs or running real background agents
- downloading media or data from the internet

Instead, describe visible local fixtures that env_build can create, such as:
- captured API response JSON
- sample request payload JSON
- command catalog JSON
- service log transcript
- mock dry-run result JSON
- redacted cookie text or normalized cookie metadata
- local status/config files
- audit manifest drafts
- pre-provided media metadata, subtitle text, or small representative text fixtures
- downloaded-response snapshots or search-result snapshots

External service names may remain as domain labels only, not as runtime dependencies.
The resulting task intent must be solvable entirely inside __TASK_ROOT__ by reading local files and writing local output artifacts.

If solution_workflow combines many external systems, collapse them into one coherent offline consolidation task over local fixture files.
Prefer one or two meaningful final artifacts over many unrelated outputs.

SYNTHESIS RULES:
- Open with the main objective immediately.
- Write 2-4 concise paragraphs only.
- Mention __TASK_ROOT__ only as the working directory or as part of required absolute output paths.
- Include required final output files and format constraints when they can be inferred from solution_workflow.
- If the workflow implies inputs but not exact files, describe the visible local fixtures env_build should provide.
- Make clear which external dependencies have been converted into local fixture data.
- The reference should help env_build choose meaningful input files, directories, and smoke checks.
- Do not mention planning, solution_workflow, model internals, tests, hidden validation, or benchmark machinery.
- No commands, scripts, tool usage instructions, algorithm descriptions, ordered steps, or headings.

Return this JSON schema exactly:
{{
  "instruction_ref_md": "valid Markdown, 2-4 concise paragraphs, no headings, no lists"
}}

INPUT JSON:
{input_json}
"""


INSTRUCTION_USER_PROMPT = """
You are an expert system engineer and benchmark task designer.

Your goal is to synthesize the final user-facing `instruction.md` for an autonomous terminal agent. The instruction must be suitable for downstream solution construction and automated validation, not merely for human-readable summarization.

INPUT PROVIDED:

1. instruction_ref

   * Internal task-intent reference.
   * Use it to infer the objective, domain, expected final state, required output files, required transformations, and output format constraints.

2. real_env_file_summary

   * Runtime-collected summary of the actual files and directories visible under __TASK_ROOT__.
   * Treat this as the authoritative source for all starting input paths.
   * It may include raw snapshots, logs, manifests, assets, repositories, configs, databases, media, or local service fixtures.

3. constraints

   * Contains task_root and prompt metadata.

CORE OBJECTIVE - PRODUCE A VERIFIABLE TASK SPECIFICATION

Rewrite instruction_ref into a coherent final instruction grounded in real_env_file_summary. The final instruction must define a clear task contract: what inputs are available, what output artifact(s) must be produced, what content each output must contain, and what constraints make the result verifiable.

Do not merely restate instruction_ref. Do not produce a loose narrative request. The generated instruction must be structured enough that a solver can implement it and a verifier can check it.

RECONCILE INTENT WITH REAL FILES

The final instruction must combine:

* The task intent from instruction_ref
* The actual available files and directories from real_env_file_summary

If instruction_ref mentions generic, hypothetical, or missing inputs, replace them with the closest real paths from real_env_file_summary. Do not invent input files that are not present. If a requested input cannot be grounded in the real environment, omit it or describe the limitation only if it is necessary for task coherence.

All important input and output paths must be absolute paths rooted at __TASK_ROOT__.

FILE ROLE MAPPING REQUIREMENT

Before writing instruction_md, internally assign every visible non-placeholder file in real_env_file_summary.task_files a functional role, such as:

* primary source
* supporting evidence
* configuration or provenance metadata
* service response snapshot
* report or analysis source
* media artifact
* generated model output
* dataset
* reference asset

If there are 12 or fewer visible non-placeholder files, the final instruction must explicitly mention every one by absolute path unless a file is clearly irrelevant metadata. If there are more than 12 files, related files may be grouped by directory or function, but every file must still be covered by a clear role.

Do not mention .gitkeep placeholders, hidden validation files, Dockerfiles, build scripts, cache files, or benchmark machinery.

TASK STRUCTURE REQUIREMENT

The final instruction should define the output in a solver-friendly and verifier-friendly way.

When the required output is a document, report, Markdown file, JSON file, CSV file, database, code artifact, image, or other structured artifact, the instruction must specify:

* the exact output path
* the required file format
* the required sections, keys, columns, tables, records, or components
* the source file(s) each required component must be derived from
* whether source content must be copied exactly, summarized, transformed, sorted, grouped, counted, filtered, or cross-referenced
* any required ordering of sections, rows, records, or entries
* any completeness requirements that a verifier can check
* any explicit exclusions, such as no external links, no network calls, or no embedded images

Avoid vague phrases such as "analyze the files", "summarize the workspace", "integrate the data", or "produce a report" unless paired with concrete output requirements.

OUTPUT PATH AND ARTIFACT RULES

* Include every required final output path implied by instruction_ref.
* If instruction_ref gives a final output path, preserve it unless it is clearly impossible under __TASK_ROOT__.
* If instruction_ref names a required deliverable but does not give an exact path, assign one concrete path under an existing output-like directory from real_env_file_summary, such as __TASK_ROOT__/output, __TASK_ROOT__/evidence, __TASK_ROOT__/reports, __TASK_ROOT__/artifacts, or __TASK_ROOT__/results.
* Each required deliverable must have exactly one explicit final path.
* Do not treat starting fixture files as final outputs unless instruction_ref clearly requires modifying an existing file in place.
* Preserve in-place modification requirements when instruction_ref explicitly requires correction or update of an existing input file.
* Use stable, descriptive filenames for inferred outputs.

VERIFICATION HOOKS REQUIREMENT

The final instruction must include enough concrete constraints to support automated validation.

For each required output artifact, include checkable requirements such as:

* required Markdown headings or section names
* required JSON keys or schema shape
* required CSV columns
* expected record grouping or sorting
* required inclusion of source-derived fields
* required count preservation
* exact filenames or path references that must appear
* whether raw source content must be preserved exactly or may be summarized
* whether media or image files should be referenced, copied, transformed, or not embedded

Do not mention hidden tests, validation internals, scoring, benchmark machinery, or evaluator implementation.

SEMANTIC INTEGRATION REQUIREMENT

The instruction must make relationships between artifacts explicit when multiple files are involved. For example:

* a health-check log validates an API specification
* a manifest provides provenance for service snapshots
* model outputs enrich or annotate a report
* a media file is generated from a service response
* a chart metadata file describes an image asset
* a transcript is summarized while raw text is preserved

Avoid generic statements like "these artifacts are related." State concrete file-to-file relationships using absolute paths.

DESCRIBE THE GOAL, NOT THE EXECUTION PROCESS

The final instruction should describe the required final observable state and verifiable output constraints. It should not prescribe an implementation procedure.

Do not include:

* shell commands
* command flags
* code snippets
* ordered execution steps
* implementation recipes
* tool usage instructions
* validation internals
* benchmark scoring details

High-level structural requirements are allowed and encouraged.

STYLE RULES

* Open with the main objective immediately.
* Write in natural Markdown prose.
* Prefer a concise structured task contract over a loose narrative.
* Headings and bullet lists are allowed only when they improve solver/verifier clarity.
* Avoid sequential process language such as "first run", "then execute", "next call", or "finally validate".
* Do not mention instruction_ref, real_env_file_summary, planning, tests, hidden validation, model internals, or benchmark generation.
* Treat external services, APIs, websites, or private systems as local snapshots only; do not ask the agent to make live network calls or authenticate.
* Mention __TASK_ROOT__ only as the root of concrete paths.

RECOMMENDED OUTPUT STYLE FOR instruction_md

When useful, structure instruction_md using concise sections such as:

* Objective
* Inputs
* Required output
* Required content
* Source-to-output mapping
* Formatting and validation constraints

Use these sections only if they make the resulting instruction clearer and more verifiable.

SELF-CHECK BEFORE RETURNING

Before returning, ensure:

* Every relevant visible file is accounted for.
* Every required output has exactly one explicit absolute path.
* The instruction is grounded only in files under __TASK_ROOT__.
* The instruction includes solver-friendly structure.
* The instruction includes verifier-friendly constraints.
* The instruction avoids commands and implementation steps.
* The instruction does not invent missing files or external dependencies.
* The output is valid JSON.

Return this JSON schema exactly:

{{
"instruction_md": "final valid Markdown instruction"
}}

INPUT JSON:
{input_json}
"""


SOLUTION_USER_PROMPT = """You are generating the reference solution artifacts for a terminal benchmark task.

Your job is to write solution/solve.sh and a small set of intentionally incomplete partial solutions.

INPUT PROVIDED:
1. instruction_md
   - The final user-facing task contract.
   - This is the primary source of truth for required outputs, exact paths, formats, schemas, sections, ordering, and negative constraints.
2. real_env_file_summary
   - Runtime-visible files and directories under the task root.
   - This is the authoritative source for available starting files.
3. selected_fixture_summaries
   - Saved fixture previews from pipeline_artifacts/share/selected_fixture_summaries.json.
   - Contains selected text fixture structure summaries and bounded content previews.
   - Use it to understand likely field names, values, counts, and relationships.
   - Treat it as a preview only; solution/solve.sh must parse the actual visible files under the task root at runtime.
4. generated_dockerfile
   - The actual Dockerfile used to build the task environment.
   - Use it to understand installed Ubuntu packages, Python packages, tools, fonts, language runtimes, and generated fixtures.
5. constraints
   - task_root, base image, and prompt metadata.

CORE GOAL:
Generate a reference solution that creates the final observable state required by instruction_md.
The tests will be generated after this solution, so solution_sh must be faithful to the task instruction and robust against later state-based validation.

PRIVATE CONTRACT EXTRACTION:
Before writing solution_sh, privately derive a concise implementation contract. Do not output it. It must include:
- task_root, preferably from constraints.task_root, else real_env_file_summary.task_root, else /task_file.
- exact output files and directories from instruction_md.
- non-literal patterns/prefixes for generated files.
- required input fixtures and their expected runtime paths.
- required JSON schemas, key order, headings, table columns, manifest structure, and metadata update rules.
- values that must be derived from local fixtures.
- values that may be synthetic but must be deterministic and cross-file consistent.
- negative constraints and forbidden content.
- installed tools/modules from generated_dockerfile.

CONTRACT PRECEDENCE AND CONFLICT RULES:
- instruction_md defines the intended task.
- real_env_file_summary defines which runtime input files exist.
- selected_fixture_summaries provide bounded fixture previews only; use them to understand schemas and examples, not as complete files.
- generated_dockerfile is authoritative for installed dependencies.
- When instruction_md is precise, follow it exactly.
- When instruction_md is vague, infer a deterministic, checkable final state from local visible fixtures and the available environment.
- Do not read tests/, validation logs, hidden files, or pipeline artifacts at runtime.

PATH AND PATTERN HANDLING:
- Normalize duplicate paths such as /task_file/output and /task_file/output/.
- Classify output paths mentioned by instruction_md as exact file, exact directory, naming prefix/pattern, or ambiguous placeholder.
- Exact files must be created.
- Exact directories must be created as directories.
- Prefix-like or pattern-like paths must not be created as literal files unless instruction_md explicitly requires that literal path. Examples include paths ending in _, paths containing <N>, *, ?, [], {{}}, or paths described as naming conventions.
- For pattern outputs such as slide_<N>.<ext>, derive concrete files from instruction_md and runtime fixtures.
- All final output paths must be absolute and rooted at task_root unless instruction_md requires relative paths inside a file.
- Create parent directories before writing outputs.

CORE RULES FOR solution_sh:
- solution_sh must be a complete bash script with:
  - #!/bin/bash
  - set -e
  - cd <task_root>
- Use the task root from constraints.task_root if present; otherwise use /task_file.
- The script must solve the task described by instruction_md, not an older planning narrative.
- The script must create every required final output at the exact absolute path requested.
- The script must derive values from visible input files under task_root; do not hard-code answers unless the value is explicitly present in the provided fixtures or instruction_md.
- The script must be deterministic. Do not use current time, random IDs, random ordering, environment-specific paths, or network state unless instruction_md explicitly requires them.
- For synthetic IDs, generate deterministic values from stable local inputs, such as a sanitized title plus a short sha256 digest of required source paths/content.
- For JSON/CSV/Markdown outputs, match exact keys, headings, order, types, and constraints described in instruction_md.
- For text fixtures, preserve exact raw text when instruction_md requires preservation.
- For JSONL fixtures, parse line by line and preserve record order when required.
- For repository/file-inspection tasks, inspect the local files in task_root at runtime.
- Prefer a single embedded Python script using python3 - <<'PY' for nontrivial parsing and output generation.
- Bash should mainly set strict mode, change directory, create directories, optionally check installed tools, and invoke Python.
- Use Python json, csv, pathlib, re, hashlib, zipfile, xml.etree.ElementTree, html, shutil, subprocess only when subprocess is genuinely needed for local installed tools.
- Do not pipe Python dict/list repr strings into json.loads. If data is needed in Python, load and transform it inside the same Python process.
- Avoid sed placeholder replacement for arbitrary extracted content because values may contain slashes, ampersands, newlines, quotes, or non-ASCII text.
- When writing embedded Python, keep code syntactically simple and directly executable.
- Avoid dynamically generating Python source code when writing JSON, text, or scripts. Use data structures, json.dumps, and plain string assembly.
- Use ensure_ascii=False when writing JSON that may contain Unicode text.
- Write machine-readable outputs with serializers rather than hand-built quoting.
- Do not copy an entire input fixture into the output unless instruction_md explicitly requires verbatim preservation.

NEGATIVE CONSTRAINTS:
- Negative constraints in instruction_md are mandatory.
- If instruction_md forbids external URLs, network references, embedded images, extra keys, backup files, placeholder text, base64, authentication, or other content, the solution must actively avoid or remove them.
- If a forbidden value appears inside an input fixture, do not copy it into the final output unless instruction_md explicitly allows that specific extracted value.
- When a negative constraint requires sanitization, the script must repair/sanitize the generated artifact before the final self-check. Do not simply detect the problem and exit.
- If external URLs are forbidden except explicitly extracted source URLs, derive the allowed URLs from the local fixtures and remove or redact all other http:// and https:// strings.
- Replace forbidden external URLs with non-URL descriptions such as [redacted external endpoint], local source-file references, hostnames without scheme, or service names.
- Do not embed binary data or base64 unless instruction_md explicitly requires it.
- Do not modify input fixtures unless instruction_md explicitly requires in-place modification.

DEPENDENCY AND TOOL RULES:
- Inspect generated_dockerfile before choosing dependencies.
- If a package, Python module, CLI tool, font, or runtime is already installed by the Dockerfile, use it directly and do not reinstall it.
- Do not assume a module is present just because it appears in fixture content, task wording, tests, or common examples.
- Prefer Python standard library and already-installed tools whenever practical.
- If solution_sh imports a non-standard Python module, the script must either confirm it is installed by generated_dockerfile or install the corresponding public package before import.
- If YAML parsing requires `import yaml`, install the public PyPI package `pyyaml` before running Python unless generated_dockerfile already installs PyYAML. The import name is `yaml`, but the package name to install is `pyyaml`.
- Prefer simple stdlib parsing for trivial YAML-like key/value files only when it is robust for the actual fixture shape; otherwise use PyYAML with explicit installation.
- Do not install dependencies when the task can be solved with standard library or installed tools.
- Do not install dependencies if instruction_md explicitly forbids package manager or network side effects.
- If a required public dependency is not installed and is genuinely necessary to solve the task, the solution may install it explicitly and minimally before use only when benchmark constraints allow public package installation. Keep installs non-interactive and public-only.
- Prefer unpinned package names for solution-installed Python packages.
- Use a >= lower bound only when the required API genuinely needs a known minimum version from verified package information.
- Do not use exact == version pins unless the input explicitly provides a verified available version.
- Do not include private indexes, direct URLs, git+ packages, local paths, browser drivers, large ML packages, GPU packages, packages requiring credentials, or packages requiring running services.
- Do not call live APIs, authenticate, or use external services.
- Do not use the network except for allowed public package installation when absolutely necessary.
- Do not instantiate heavy services such as ChromaDB servers or embedding models if the task only requires updating a JSON metadata snapshot.

DATA SHAPE RULES:
- Treat real_env_file_summary as an inventory, not a complete schema.
- Treat selected_fixture_summaries as previews, not complete schemas.
- At runtime, parse the actual visible files under task_root.
- Do not write embedded Python that imports a library without an explicit `import` statement in that same Python program.
- Guard nested JSON/YAML/CSV-derived values with type checks before calling methods such as .get, iterating records, or indexing by key.
- Normalize uncertain values with small helper functions such as:
  - object_or_empty_dict
  - list_or_empty_list
  - string_or_empty_string
  - number_or_none
- If a field may be absent or represented in multiple shapes, write tolerant extraction logic while still producing the exact required output schema.
- If instruction_md requires exact field names or case-sensitive matching, respect that exactness. Do not alias field names unless instruction_md permits it.
- Use stable sorting only when instruction_md requires sorted output. Otherwise preserve source order when it is meaningful.

JSON OUTPUT RULES:
- Write valid RFC 8259 JSON encoded in UTF-8.
- Use json.dumps with indent=2 unless instruction_md requires compact JSON.
- Preserve required top-level key order by constructing dicts in the required order.
- Ensure booleans are booleans, numbers are numbers, strings are strings, arrays are arrays, and objects are objects.
- If instruction_md says no extra keys are allowed, emit exactly the required keys at that level.
- If a JSON output is a manifest of generated files, ensure every listed file exists before final self-check exits.
- If a JSON output extends an input metadata snapshot, preserve original entries unchanged by stable ID when available. Add new entries without mutating existing entry objects.
- Keep counters such as total_documents consistent with actual document list length when present.

MARKDOWN OUTPUT RULES:
- Emit a clear top-level heading when a Markdown document is required.
- Include required level-2 headings exactly and in order when specified.
- Do not add extra level-2 headings if instruction_md says the listed sections are exact.
- Include required metadata labels exactly when specified.
- For local file URLs, use file:// URLs pointing to the required output path when required.
- For verbatim raw context, read the source file as text and place the exact contents inside a fenced code block. Preserve line order and content.
- For required tables, include the exact required column labels and rows for required entities.
- Avoid placeholder prose such as TODO, TBD, placeholder, lorem ipsum, sample text, dummy, or N/A when a real value can be derived.
- Do not embed images in Markdown unless instruction_md explicitly requires it. Use local paths or URLs only when allowed.

PPTX AND DOCUMENT OUTPUT RULES:
- For .pptx outputs, if python-pptx is installed by generated_dockerfile, use it when useful.
- Prefer loading the provided template as the base when instruction_md requires applying a template.
- Preserve slide count and slide order from the runtime presentation specification.
- Add representative slide titles and required content from the presentation spec.
- Ensure the final PPTX is a valid ZIP/OPC package with [Content_Types].xml, ppt/presentation.xml, and ppt/slides/slide*.xml.
- If exact visual fidelity is not asserted, prioritize a valid presentation with correct slide count, order, titles, and content over brittle theme internals.
- For .docx outputs, use installed libraries or ZIP/OOXML generation as appropriate, and ensure a valid package.
- For PDF outputs, produce a valid PDF with %PDF header when required.

SLIDE IMAGE RULES:
- If rendered slide images are required, create exactly one valid image file per slide with the required naming convention.
- Prefer actual local rendering from the final presentation using installed tools such as LibreOffice, ImageMagick, Poppler, or Python libraries when available and reliable.
- If headless rendering is unavailable but the verifier only checks file existence, naming, manifest consistency, and image magic bytes, create deterministic valid placeholder-like slide images containing the slide index/title/content. They must not be empty and must correspond to the required slide count.
- Use allowed formats from instruction_md, preferably PNG when Pillow is installed or SVG when text-only generation is sufficient and allowed.
- Write images directly in the required output directory when specified.
- Build the slide image manifest from the actual generated image paths, ordered by slide index.
- Validate every manifest path exists and has the expected extension/magic bytes before exiting.

CSV/SPREADSHEET RULES:
- For CSV/TSV, use Python csv module.
- For XLSX, use openpyxl only if installed or if installation is absolutely necessary and allowed. Otherwise use ZIP/XML only if practical.
- Ensure required sheets, headers, and rows are present.

RUNTIME ROBUSTNESS RULES:
- Do not rely on environment variables unless instruction_md explicitly requires them.
- If an optional environment variable is useful, provide a deterministic fallback derived from inputs.
- Create required parent directories before writing outputs.
- Prefer writing all outputs from one Python process so parsing, transformation, serialization, and validation share the same in-memory data.
- Add preflight checks for required input files and required installed tools/modules when they are needed.
- Add post-write self-checks that parse or inspect final output artifacts and verify required paths, schemas, core invariants, and negative constraints before exiting.
- The final self-check should fail fast with clear error messages if a required artifact is missing or invalid.
- Ensure repeated runs are idempotent: overwrite or update generated outputs deterministically without accumulating duplicate metadata entries or stale files.
- Remove or overwrite stale generated files that would break exact manifest/image count checks when rerunning solve.sh.

SELF-CHECK REQUIREMENTS INSIDE solution_sh:
Include lightweight self-checks appropriate to the task. Examples:
- Required output files exist and are non-empty.
- JSON outputs parse and have required keys/order.
- Markdown outputs contain required headings and metadata labels.
- PPTX outputs are valid ZIP packages with required core parts.
- Image manifest paths exist and image magic bytes are valid.
- Metadata updates preserve original entries and include new required references.
- Raw context or other verbatim text is preserved exactly when required.
- Forbidden strings such as http:// or https:// are absent when instruction_md forbids external URLs, except explicitly allowed extracted values.
- Input files still exist when instruction_md forbids modifying them.

PARTIAL SOLUTION RULES:
- Generate 1-3 executable partial scripts.
- Each partial must be plausible but intentionally incomplete.
- Each partial should usually exit 0 after creating incomplete or wrong artifacts, so robust validation fails because the final state is wrong, not because the partial script crashes.
- Each partial should create at least one artifact that resembles part of the required output.
- Each partial must fail robust validation by missing a required artifact, omitting required sections/keys, using wrong counts, failing cross-file consistency, not preserving original metadata, skipping generated images, or using placeholder content.
- Partial scripts must not read tests/, validation logs, hidden files, or pipeline artifacts at runtime.
- Partial scripts must not install packages, use the network, authenticate, or call live services.
- Partial scripts must be deterministic and safe.
- Good partial examples:
  - creates the main JSON/Markdown but omits one required section,
  - creates a PPTX but no slide image manifest,
  - creates a manifest with only one image,
  - updates metadata but mutates original entries,
  - writes placeholder values instead of fixture-derived values.

OUTPUT REQUIREMENTS:
- Return one valid JSON object and nothing else.
- Do not wrap the JSON in Markdown fences.
- Do not include explanatory text before or after the JSON.
- The response must be parseable by json.loads.
- solution_sh must be a JSON string containing a complete bash script.
- solution_sh must start with exactly #!/bin/bash.
- solution_sh must include set -e and cd <task_root>.
- partials must be a JSON array of 1-3 objects.
- Each partial object must have:
  - name: a safe filename ending in .sh,
  - content: a complete bash script starting with #!/bin/bash, including set -e and cd <task_root>.
- Escape newlines correctly inside JSON strings.
- Do not include comments outside the returned JSON object.

SELF-CHECK BEFORE RETURNING:
- Ensure the returned JSON is valid.
- Ensure solution_sh starts with #!/bin/bash, includes set -e, and changes into the task root.
- Ensure every helper referenced by embedded Python code is defined.
- Ensure embedded Python code is syntactically valid.
- Ensure every Python module used by embedded Python code is explicitly imported before use.
- Ensure every non-standard Python module imported by solution_sh is installed first or already present in generated_dockerfile. For YAML, install `pyyaml` before `import yaml` unless PyYAML is already installed.
- Ensure solution_sh does not read tests/, hidden evaluator files, validation logs, or pipeline artifacts at runtime.
- Ensure solution_sh does not use live APIs, credentials, or network services.
- Ensure solution_sh creates every exact required output file and directory.
- Ensure solution_sh handles pattern outputs by creating concrete files, not literal prefix files.
- Ensure solution_sh uses installed dependencies or standard library, and installs nothing unless genuinely necessary and allowed.
- Ensure partial scripts are plausible, executable, incomplete, and safe.

Return this JSON schema exactly:
{{
  "solution_sh": "#!/bin/bash\\nset -e\\ncd /task_file\\n...",
  "partials": [
    {{"name": "partial_solve_missing_case.sh", "content": "#!/bin/bash\\nset -e\\ncd /task_file\\n..."}}
  ]
}}

INPUT JSON:
{input_json}
"""


TEST_USER_PROMPT = """You are a senior Python engineer who writes robust pytest suites for terminal-agent benchmarks.

You are generating tests WITH a generated reference solution available as context.

INPUT PROVIDED:
1. instruction_md
   - Final user-facing task instruction.
   - Primary source of truth for required final observable state, exact output paths, formats, schemas, ordering, sections, and negative constraints.
2. real_env_file_summary
   - Runtime-visible files and directories under the task root.
   - Source of truth for starting input paths and available local fixtures.
3. selected_fixture_summaries
   - Saved fixture previews from pipeline_artifacts/share/selected_fixture_summaries.json.
   - Contains selected small text fixture contents or structure summaries.
   - Use these only to understand likely fixture shape and choose deterministic checks.
   - Do not treat previews as complete files; generated tests must parse the actual runtime fixture files.
4. environment_metadata
   - Empty output-like directories and environment readiness metadata.
5. generated_dockerfile
   - The actual Dockerfile used to build the task environment.
   - Use it to determine which tools and libraries are already installed.
6. generated_solution
   - The generated solution/solve.sh for this task.
   - Use it as generation-time reference context to understand expected derivations, output paths, schemas, and edge cases.
   - Do not make test_state_py read solution files at runtime.

CORE RULE:
Generate state-based pytest tests that validate the final observable state after an agent completes the task.
Do not assume access to a reference solution.
Do not invent expected values that cannot be derived from instruction_md or local runtime fixtures.

PRIVATE CONTRACT EXTRACTION:
Before writing tests, privately derive a concise validation contract from the input JSON. Do not output this contract. It must include:
- task_root, preferably from constraints.task_root, else real_env_file_summary.task_root, else /task_file.
- exact required output files from instruction_md.
- exact required output directories from instruction_md.
- non-literal naming patterns and prefixes.
- in-place modification targets, if any.
- required schemas, top-level key order, section headings, required records, row counts, manifest rules, and cross-file consistency rules.
- source fixtures used to derive each assertion.
- negative constraints such as no network references, no embedded images, no extra keys, no input modification, no placeholders, or no base64.
- available verifier-side libraries from generated_dockerfile.
- reference behavior implied by generated_solution, without testing implementation-specific internals.

SOURCE TRUST AND CONFLICT RULES:
- instruction_md is the primary source of truth for final required behavior.
- real_env_file_summary is authoritative for starting input files and directories.
- selected_fixture_summaries are previews; use them to identify likely field names and content patterns, but tests must read the actual files under task_root at runtime.
- generated_dockerfile is authoritative for installed packages/tools only.
- generated_solution is a useful reference for intended derivations and concrete outputs, but tests must validate final state rather than implementation details.
- If instruction_md explicitly requires an exact field name, exact key, exact heading, or exact path, do not silently substitute aliases unless instruction_md allows aliases.
- If a required exact field is absent from the runtime fixture, tests should compute the resulting required state according to the instruction. For example, if an exact credential key is missing and the instruction says the check is exact and case-sensitive, the derived boolean should be false and the extracted value should be empty or absent according to the required output schema.
- If instruction_md is vague but fixture schema is clear, derive a reasonable deterministic assertion from the runtime fixture.
- If instruction_md is vague and generated_solution clarifies output shape or derivation, use that clarification only when it is consistent with the instruction and local fixtures.
- If a value can be represented in multiple valid ways and instruction_md does not constrain it, assert presence, type, parseability, non-placeholder content, and cross-file consistency rather than a single exact representation.

TEST STRATEGY:
- Prefer assertions about required output existence, non-empty content, file format, parseability, paths, schema shape, required sections, required records, and cross-file consistency.
- Tests must be nop-safe: an untouched environment should fail because required final outputs are missing or unchanged.
- For JSON outputs, test parseability, exact top-level keys when specified, key order when specified, required nested keys, value types, record counts, and values derived from runtime fixtures.
- For CSV/TSV outputs, test parseability, headers, non-empty records, required columns, and values derived from runtime fixtures.
- For Markdown outputs, test required sections, heading order, metadata blocks, referenced local paths/entities, verbatim copied content when required, and absence of obvious template placeholders.
- For binary document outputs, test file existence, minimum size, magic/header bytes or ZIP package structure when possible.
- For in-place modification tasks, test that the target file remains parseable or structurally valid and reflects the required final state.
- Test that outputs are not empty placeholders and are not simple copies of one input fixture when the task requires consolidation, filtering, normalization, rendering, merging, or audit synthesis.
- If real input files expose stable IDs, URLs, domains, names, filenames, prompt IDs, statuses, or evidence labels that instruction_md requires in the final output, assert that representative required entities appear.
- Do not fail solely because harmless extra files exist unless instruction_md explicitly forbids extra files or requires an exact directory listing.

PATH AND PATTERN HANDLING:
- Normalize duplicate paths such as /task_file/output and /task_file/output/.
- Classify each output path from instruction_md as one of:
  1. exact file,
  2. exact directory,
  3. naming prefix or pattern,
  4. ambiguous placeholder.
- Exact files must be asserted directly.
- Exact directories should be asserted as directories only; do not treat a directory as a content-complete artifact unless instruction_md requires an exact directory listing.
- Prefix-like, glob-like, placeholder-like, or incomplete paths must not be asserted as literal files. Examples include:
  - paths ending in _
  - paths containing <N>, <name>, *, ?, [], {{}}, or similar placeholders
  - paths that instruction_md describes as a naming convention
  - paths that are only a stem for generated numbered artifacts
- For pattern outputs, derive concrete expected files from instruction_md and runtime fixtures. For example, slide_<N>.<ext> should be validated by globbing allowed extensions and comparing indexes/counts against the slide count derived from the presentation specification or final document.
- All asserted output paths must be absolute and rooted at task_root unless instruction_md explicitly requires relative paths inside a manifest.

DERIVED ASSERTION RULES:
- When an expected value comes from an input fixture, parse it from that fixture at test runtime instead of hard-coding a value from prompt context.
- Do not hard-code values solely copied from selected_fixture_summaries.content_preview unless instruction_md requires that exact literal and the test also verifies it against the runtime fixture.
- If a fixture contains multiple similar candidate values, choose the one matching instruction_md terminology. For example, a resolved or external machine IP should come from a line like External IP resolved, not Local IP assigned, unless instruction_md explicitly says local IP.
- For JSON fixtures, load the real file and derive expected fields, IDs, counts, statuses, names, ordering, and booleans from parsed data.
- For JSONL fixtures, parse line by line and preserve record order when instruction_md requires order.
- For text/log fixtures, use regex tied to instruction wording rather than hard-coded prompt text.
- For fixture-derived counts shared by multiple outputs, derive once in helper functions and reuse consistently.
- For presentation tasks, derive expected slide count primarily from len(slides) in the runtime presentation spec. If metadata.total_slides exists, assert it is consistent with len(slides) before using it or use len(slides) as source of truth.
- For synthetic identifiers required by instruction_md, do not assert an exact value unless instruction_md gives one. Assert that the identifier exists, is non-empty, is not an obvious placeholder, and is reused consistently across outputs when cross-file linkage is required.
- Obvious placeholder strings include TODO, TBD, FIXME, placeholder, lorem ipsum, sample text, dummy, unknown when a value must be known, and N/A when a value must be present.

CONTRACT PRECEDENCE:
- instruction_md is authoritative for required output artifacts and in-place modification targets.
- If instruction_md forbids modifying input files, include a lightweight check that required input fixtures still exist and are non-empty. Verify hashes only when a fixture manifest provides trustworthy hashes for those exact files.
- Do not test hidden files, tests, validation logs, pipeline artifacts, or solution files.
- Do not assume output-like directories are required outputs unless instruction_md explicitly requires them.

JSON-SPECIFIC RULES:
- Use json.load/json.loads from the Python standard library.
- If instruction_md says a JSON object has exact top-level keys, assert exact key set and exact order using list(data.keys()).
- If instruction_md says no additional keys are permitted, assert exact keys at that level only.
- Assert booleans are bool, numbers are int/float and not strings, arrays are lists, objects are dicts.
- If a manifest lists generated files, verify each listed path exists at the expected location and matches required path/root constraints.
- If a JSON output extends an input JSON snapshot, verify original entries are preserved unchanged by stable ID when available, while allowing explicitly update-like fields such as counters, snapshot timestamps, or versions to change only when instruction_md permits or requires them.
- If total/count fields exist, assert they equal the actual length of their associated arrays when instruction_md implies consistency.
- If external URLs are forbidden except specific extracted fixture URLs, derive the allowed URLs from the runtime fixtures and assert no other http:// or https:// strings occur in the output.

MARKDOWN-SPECIFIC RULES:
- Validate ordered level-2 headings (## ...) for required Markdown sections unless instruction_md explicitly specifies another heading level or all heading levels.
- Allow a single unspecified top-level heading if instruction_md references a top-level heading but does not give exact text.
- If instruction_md says sections are exact, assert the level-2 heading list is exactly the required headings in order. Allow lower-level headings only when instruction_md requires subsections or tables.
- For required metadata blocks, assert required labels exist and values are non-empty, non-placeholder, and correctly formatted.
- For local file URLs, validate the scheme and resolved path. For example, file:///task_file/output/audit_document.md should resolve to the required Markdown output path.
- When instruction_md requires verbatim source text inside a Markdown fenced code block:
  - read the source text at runtime,
  - locate the target section by heading,
  - extract the first fenced code block inside that section,
  - compare the code block body to the source text,
  - allow at most insignificant surrounding newlines introduced by Markdown fencing,
  - do not allow changed, removed, reordered, or summarized source lines.
- For required Markdown tables, validate the header row contains the required columns. Do not require exact whitespace/alignment unless instruction_md requires it.
- Do not require exact prose wording unless instruction_md requires exact wording.

DOCX RULES:
- For .docx outputs, use Python stdlib zipfile and XML/string inspection when possible.
- Validate that the file is a ZIP package with [Content_Types].xml and word/document.xml.
- For .docx text checks, inspect relevant word/*.xml files, including document, headers, and footers.
- Page numbers may live in footer/header XML; styles may live in word/styles.xml.
- For .docx image checks, look for word/media/* or relationship targets when generated or embedded images are required.
- Avoid overly exact OOXML placement assumptions unless instruction_md specifies the exact XML representation.

PPTX RULES:
- For .pptx outputs, prefer Python stdlib zipfile and XML/string inspection unless an already-installed library materially improves correctness.
- Validate that the PPTX is a ZIP package containing [Content_Types].xml, ppt/presentation.xml, and ppt/slides/slide*.xml.
- Derive expected slide count from the runtime presentation spec, preferably len(slides).
- Validate that the number of slide XML files matches the expected slide count.
- When slide titles or required text are specified in the draft JSON, inspect slide XML text content and ensure representative titles/content appear in slide order.
- Do not require exact OOXML relationship IDs, layout IDs, theme IDs, placeholder IDs, shape coordinates, font names, or style IDs unless instruction_md explicitly requires them.
- If template application is required, prefer robust checks such as valid PPTX package, expected slide count/content, and output not being byte-identical to the template when content transformation is required. Avoid brittle theme XML assertions unless instruction_md requires them.

SLIDE IMAGE AND IMAGE MANIFEST RULES:
- If instruction_md requires one rendered image per slide, derive slide count from the presentation spec or final PPTX and require exactly one image per slide.
- If a slide image manifest schema is specified, validate it exactly. For example, if instruction_md says the manifest has a single key images, assert list(manifest.keys()) == ["images"].
- Manifest image paths must be strings, absolute, rooted under task_root, unique, and ordered by slide index when ordering is required.
- If instruction_md says images must be written directly into the output directory, assert each manifest path's parent is exactly that output directory.
- Filenames should match the required naming convention such as slide_<N>.<ext> with 1-based contiguous indexes.
- Extensions must be limited to formats allowed by instruction_md, such as png, jpg, jpeg, svg, or webp.
- Verify each listed image exists and is non-empty.
- Use lightweight magic/header validation:
  - PNG starts with b"\\x89PNG\\r\\n\\x1a\\n"
  - JPEG starts with b"\\xff\\xd8"
  - WebP starts with RIFF and contains WEBP at bytes 8:12
  - SVG is UTF-8/XML-like text containing <svg
- Do not use visual similarity, OCR, pixel-perfect comparison, or live rendering in tests.

PDF RULES:
- For .pdf outputs, at minimum validate existence, non-empty size, and header bytes starting with %PDF.
- If text extraction is necessary and no installed dependency exists, include a small public PyPI package only when standard library checks are insufficient.
- Avoid asserting exact pagination, font metrics, or rendering artifacts unless instruction_md explicitly requires them.

SPREADSHEET RULES:
- For .xlsx outputs, prefer zipfile/XML inspection or openpyxl if installed or listed in packages.
- Validate workbook ZIP structure, expected sheet names, required headers, and non-empty data rows.
- Do not require exact column widths, styles, or calculation cache values unless instruction_md requires them.
- For .csv/.tsv, use the csv standard library and validate delimiter, headers, and record consistency.

METADATA AND INDEX UPDATE RULES:
- For metadata snapshots that must preserve existing entries:
  - load the original and updated JSON at runtime,
  - identify stable IDs such as doc_id, id, path, url, or name,
  - assert each original document/entry object is present unchanged in the updated list,
  - do not require exact list order unless instruction_md requires it,
  - allow top-level counters or update timestamps to change only when logically update fields,
  - assert new required references appear.
- If an audit document URL and slide image paths are required to be added to metadata, extract them from the generated audit document and slide image manifest, then assert the updated metadata references them.
- Do not instantiate databases, embedding models, or external services during tests when the output is a JSON metadata snapshot.

NETWORK, LOG, AND PORT PARSING RULES:
- For text/log fixtures involving explicit labels such as unknown, failed, resolved, external, healthy, unhealthy, deleted, cancelled, recognized, or valid, prefer the explicit labels present in the fixture over broad external knowledge.
- For network-port tasks, parse the runtime text file for listening entries using status markers such as (LISTEN), protocol tokens, process/service names, and port numbers.
- Avoid asserting a large hard-coded catalog of standard ports unless instruction_md or fixtures provide that catalog.
- If instruction_md says "unknown listening ports", prefer lines explicitly marked with unknown process/service names or unknown users, then validate required port/protocol/process values appear in the output.

BOUNDARIES:
- Do not inspect solution/solve.sh, tests internals, hidden files, validation logs, build scripts, or pipeline artifacts at test runtime.
- test_state_py must not run commands, shell tools, services, live network calls, package managers, or the agent solution.
- Do not use subprocess, os.system, pexpect, requests, urllib network calls, database servers, browsers, CLIs, or package managers in test_state_py.
- Dependency installation is allowed only in tests/test.sh before pytest starts, using the public package list returned in packages.
- Do not depend on live APIs, external systems, current time, random order, package manager output, internet connectivity, GPUs, private credentials, or locale-specific sorting.
- Do not check implementation-specific strings that are not required by instruction_md.
- Do not assert that solution source code contains a specific implementation detail.
- Do not overfit to wording from prompt context unless the final instruction requires that evidence.
- Use absolute paths rooted at task_root.
- Keep tests focused: generate 4-8 meaningful pytest functions total when practical. If one artifact has many independent required sections, use helper functions and group related section checks into fewer tests rather than creating one test per field. Cover each required output artifact at least once.

DEPENDENCY RULES:
- packages may include small public PyPI packages for verifier-side parsing or inspection only.
- Prefer the Python standard library for simple JSON, CSV, Markdown, ZIP, XML, image magic-byte, and text/log checks.
- Every module name used in test_state_py must be explicitly imported in test_state_py before use, including pytest.
- If test_state_py uses `pytest.fixture`, `pytest.mark`, `pytest.raises`, `pytest.fail`, `pytest.skip`, or any other `pytest.*` API, it must include `import pytest` near the top of the file.
- If test_state_py uses any third-party library, it must both import that library in the Python file and ensure the corresponding package is installed by generated_dockerfile or listed in packages.
- If generated_dockerfile installs a Python library, test_state_py may import and use it when appropriate, but the library must not be repeated in packages.
- If a format can be checked reliably with the standard library, prefer the standard library even when heavier packages are installed.
- Include a package only when it materially improves correctness for formats such as JSON5, YAML, PDF text extraction, DOCX/PPTX inspection, image inspection, or HTML parsing.
- Do not use exact == version pins.
- Prefer an unpinned package name. Use a >= lower bound only when the input explicitly provides a verified available version or the generated tests require an API introduced in a known minimum version.
- Do not invent version numbers from examples or general knowledge.
- Do not include private indexes, direct URLs, git+ packages, local paths, browser drivers, large ML packages, packages requiring GPUs, packages requiring credentials, or packages requiring running services.
- Prefer [] when standard library checks are sufficient.

SELF-CHECK BEFORE RETURNING:
- Ensure test_state_py starts exactly with the required canary line.
- Ensure test_state_py would pass ast.parse.
- Ensure every helper function referenced by a test is defined.
- Ensure every module or library referenced by name in test_state_py is explicitly imported in test_state_py.
- Ensure `import pytest` is present whenever the code uses `pytest.` or decorators such as `@pytest.fixture` / `@pytest.mark.parametrize`.
- Ensure every imported third-party package is either installed by generated_dockerfile or listed in packages.
- Ensure no test calls subprocess, os.system, shell tools, network clients, package managers, services, or the agent solution.
- Ensure every required output artifact is covered by at least one assertion.
- Ensure an untouched environment would fail because required outputs are absent or unchanged.
- Ensure a compliant state would pass without relying on current time, randomness, network, hidden files, or exact non-required formatting.
- Ensure tests derive expected fixture values from runtime files, not from selected_fixture_summaries.content_preview.

OUTPUT REQUIREMENTS:
- Return one valid JSON object and nothing else.
- Do not wrap the JSON in Markdown fences.
- Do not include explanatory text before or after the JSON.
- The response must be parseable by json.loads.
- packages must be a JSON array of public PyPI package strings that tests/test.sh may install before running test_state_py, beyond pytest and pytest-json-ctrf.
- test_state_py must be a JSON string containing the complete Python pytest file with escaped newlines.
- test_state_py must start exactly with: # HARBOR_CANARY: tests generated by FACET-Terminal
- Include clear assertion messages.

Return this JSON schema exactly:
{{
  "packages": [],
  "test_state_py": "# HARBOR_CANARY: tests generated by FACET-Terminal\\nfrom pathlib import Path\\n..."
}}

INPUT JSON:
{input_json}
"""


REPAIR_PROMPT = """You repair FACET-Terminal Harbor-style terminal benchmark tasks.
Return only valid JSON. Do not include Markdown fences, comments, or extra keys.

Repair this generated FACET-Terminal task after Docker validation failed.

INPUT PROVIDED:
1. validation_summary
   - Compact report for docker build, oracle solution, no-op trial, and partial trials.
2. task_files
   - Current text excerpts from instruction.md, solution/solve.sh, tests/test_state.py, tests/test.sh, environment/Dockerfile, task.toml, and useful pipeline summaries.
3. supporting_artifacts
   - Excerpts from visible starting fixtures under environment/task_file and shared planning summaries.
   - Treat these as generation-time evidence for real fixture shape. Runtime solution/tests must read actual files under __TASK_ROOT__.
4. diagnosis_static
   - Heuristic path/schema/test-scope findings.
5. previous_rounds
   - Earlier repair attempts and validation results.
   - On later rounds, prioritize the newest remaining oracle/test failure over the original failure.

FAILURE-FIRST DECISION TREE:
- Treat current_failure_digest and the newest validation_summary as the source of truth for the current round.
- If Docker build failed, fix only the concrete build error and use environment/Dockerfile only when it appears in repair_policy.effective_allowed_patch_targets.
- If oracle solution exited nonzero, fix the exact exception in solution/solve.sh first. Do not modify tests/test_state.py or instruction.md while the solution still crashes.
- If pytest collection or dependency setup failed, fix tests/test.sh so dependencies are installed into the same environment that runs pytest.
- If oracle solution exited zero but pytest assertions failed, fix solution output first. Modify a test only when it contradicts instruction.md, parses a fixture using a nonexistent field, or checks implementation details instead of final observable state.
- If a partial solution received reward 1, inspect that exact partial script and add an assertion that directly detects its intentional omission or wrong value. Do not weaken unrelated assertions.

PATCH TARGET ENFORCEMENT:
- Return only paths listed in repair_policy.effective_allowed_patch_targets.
- Any other path will be rejected and must not appear in files_to_replace, files_to_add, or files_to_delete.
- Do not propose environment/Dockerfile for an oracle, pytest, no-op, or partial failure when it is absent from the effective list.

ROUND CONVERGENCE:
- repair_policy.round identifies the current round and whether this is the final round.
- If the current error signature is unchanged from a previous round, the previous strategy failed. Do not return identical file content or repeat the same claimed fix.
- State why the previous patch failed and make a materially different, smaller change aimed at the exact remaining exception or assertion.
- Preserve all unrelated content in files that must be replaced; do not regenerate a whole file from a generic template.
- Every repair_strategy item must name the exact error, failed test, or passing partial that the change is expected to resolve.
- On the final round, choose the smallest unresolved failure and fix it completely instead of broadening the rewrite.

DEPENDENCY ENVIRONMENT RULES:
- A package installed outside uvx is not automatically visible inside uvx's isolated pytest environment.
- Verifier dependencies must be supplied to the same interpreter/environment that runs pytest.
- Avoid exact optional-package pins unless validation evidence shows that version is available for the current Python ABI and package index.
- For a solution runtime dependency under oracle_failed, prefer the Python standard library or bootstrap the dependency inside solution/solve.sh; a Dockerfile patch will not be applied unless build_failed made it effective.

TEST INTEGRITY:
- A failing oracle is not evidence that the test is wrong.
- Preserve every requirement explicitly stated in instruction.md.
- Before changing tests/test_state.py, cite exact evidence in failure_analysis.evidence showing a contradiction, invalid fixture-field assumption, or implementation-detail assertion.
- Never remove or relax an assertion merely to make the oracle pass.

CORE GOAL:
Make the smallest useful patch so the repaired task passes the same validation contract:
- oracle/reference solution reward must be 1
- no-op reward must be 0
- every partial solution reward must be 0 or fail before reward because it is incomplete

REPAIR RULES:
- Preserve the task intent and visible starting fixtures.
- Maintain alignment among instruction.md, solution/solve.sh, tests/test_state.py, and tests/test.sh.
- If tests enforce a required output path, schema, heading, count, or relationship, instruction.md must explicitly require it.
- If tests assert implementation details not required by instruction.md, relax or rewrite tests to validate final observable state instead.
- If oracle failed, prefer fixing solution/solve.sh or missing dependency bootstrap in tests/test.sh before changing tests.
- If oracle solution exits nonzero, fix that runtime exception first. If oracle reaches pytest and only a few assertions fail, mirror the pytest's runtime derivation logic in solution/solve.sh.
- If no-op or a partial passed, strengthen tests so incomplete work fails; do not weaken the reference solution.
- Use supporting_artifacts to understand actual JSON/CSV/Markdown/log schemas. Do not assume a fixture is valid JSON only because its filename ends in .json; handle malformed or semi-structured fixtures when the current files show that shape.
- When repairing after a previous round, use the latest validation_summary as the current source of truth and make a targeted patch for the remaining failing assertions.
- Do not create final answer files in environment/ or task fixtures.
- Do not read hidden files, pipeline artifacts, validation logs, tests, or solution internals at runtime from solution/solve.sh.
- Do not introduce live API calls, authentication, current-time dependence, randomness, or private services.
- Tests must inspect final filesystem state only. They must not run solution code, shell commands, subprocesses, services, package managers, or network clients.
- tests/test.sh may install small public verifier packages if needed. tests/test_state.py itself must not install packages.
- If solution/solve.sh imports a non-standard Python module, it must install the corresponding public package before import only when allowed and genuinely necessary; prefer Python standard library.
- Keep patches focused. Do not rewrite the whole task unless alignment is badly broken.
- Do not delete or change starting fixtures unless instruction.md explicitly requires in-place modification.
- Do not add unrelated files, caches, backups, logs, or benchmark machinery.

Do not modify environment/task_file/** except to remove accidentally generated final answer files. If a fixture itself is invalid, prefer making tests/solution handle the actual fixture shape.

RETURN JSON SCHEMA EXACTLY:
{{
  "summary": "short repair summary",
  "failure_analysis": {{
    "primary_failure_type": "...",
    "root_cause": "...",
    "evidence": ["exact exception, failed test, or fixture field"],
    "previous_attempt_failure": "why the previous round did not resolve the current failure, or empty on round 1",
    "preserve": ["task intent or files to preserve"]
  }},
  "repair_strategy": ["small concrete changes"],
  "files_to_replace": [
    {{"path": "solution/solve.sh", "content": "#!/bin/bash\\nset -e\\ncd __TASK_ROOT__\\n..."}}
  ],
  "files_to_add": [],
  "files_to_delete": [],
  "infeasible": false
}}

INPUT JSON:
{input_json}
"""


def render_prompt(template: str, context: dict[str, Any], *, task_root: str, base_image: str) -> str:
    rendered = template.replace("__TASK_ROOT__", task_root).replace("__BASE_IMAGE__", base_image)
    if "{INPUT_JSON}" in rendered:
        return rendered.replace("{INPUT_JSON}", json.dumps(context, ensure_ascii=False, indent=2))
    return rendered.format(input_json=json.dumps(context, ensure_ascii=False, indent=2))
