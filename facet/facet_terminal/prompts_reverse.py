from __future__ import annotations

import json
from typing import Any


REVERSE_INSTRUCTION_USER_PROMPT = """You are an expert system engineer and benchmark task designer.

Your goal is to synthesize a complete task-planning bundle for an autonomous terminal benchmark.

The bundle must contain three aligned fields:

1. `instruction_md`
   - The final user-facing Markdown instruction for the autonomous terminal agent.
   - It defines the required final observable state.
   - It must be suitable for downstream solution construction and automated validation.
   - It must not mention tests, hidden validation, benchmark machinery, prompt generation, internal planning, or the existence of hints.

2. `solution_hint`
   - A private canonical construction plan for the later reference-solution generator.
   - It must explain how to construct the required final artifacts from the local inputs named in `instruction_md`.
   - It must identify source roles, extraction targets, transformations, ordering rules, cross-references, formatting requirements, and likely solution pitfalls.
   - It is not optional advice; downstream solution generation will treat it as the main implementation plan.
   - It must not add deliverables or requirements that are absent from `instruction_md`.

3. `test_hint`
   - A private canonical validation plan for the later test generator.
   - It must explain what automated tests should verify, which artifacts matter, which values should be derived from local source files, which counts/orderings/cross-references must hold, and which common failure modes should be caught.
   - It is not optional advice; downstream test generation will treat it as the main validation plan.
   - It must not add deliverables or requirements that are absent from `instruction_md`.

INPUT PROVIDED:

The input JSON contains:
- a task-intent reference, usually under a key such as `instruction_ref`;
- an inventory or summary of visible local files and directories under `/task_file`;
- optional metadata about the prompt or task environment.

Use the task-intent reference to infer the intended objective, domain, required final state, required outputs, transformations, and exclusions.

Use the visible local file inventory as the authoritative source for available starting files. If the input contains multiple summaries, prefer the concrete visible file paths under `/task_file`.

Do not invent input files. Do not refer to files that are not visible in the provided input JSON. Do not rely on external services, external websites, authentication, live APIs, hidden files, or benchmark machinery.

CORE OBJECTIVE:

Generate a coherent task bundle that makes the later solution and test stages agree on the same task.

The bundle must define:
- what local input files are available;
- what role each relevant input file plays;
- what final output artifact or artifacts must be produced;
- the exact absolute path of each final output artifact;
- the required format and structure of each output;
- how each output component is derived from the local inputs;
- what ordering, grouping, counting, filtering, summarization, copying, or cross-referencing is required;
- what exclusions or negative constraints apply;
- how the later solution should construct the result;
- how the later tests should validate the result.

The `solution_hint` and `test_hint` must act as shared plans for later stages, not as vague summaries.

GROUNDING RULES:

- All concrete paths in all three fields must be absolute paths rooted under `/task_file`.
- If the task intent names hypothetical or generic files, replace them with the closest visible real files from the provided input JSON.
- If a requested source cannot be grounded in visible local files, omit it unless mentioning the limitation is necessary for task coherence.
- If a final output path is specified by the task intent, preserve it when it is under `/task_file`.
- If the task intent names a deliverable but gives no exact path, assign exactly one concrete path under an existing output-like directory when available, such as `/task_file/output`, `/task_file/reports`, `/task_file/results`, `/task_file/artifacts`, or `/task_file/evidence`.
- Do not treat starting fixture files as final outputs unless the task intent explicitly requires modifying an existing file in place.
- Preserve explicit in-place modification requirements when the task intent clearly requires correction or update of an existing input file.
- Use stable, descriptive filenames for inferred outputs.

FILE ROLE MAPPING:

Before writing the final JSON, privately assign every visible non-placeholder input file a functional role, such as primary source, supporting evidence, configuration or provenance metadata, service response snapshot, report or analysis source, media artifact, generated model output, dataset, or reference asset.

If there are 12 or fewer visible non-placeholder files, `instruction_md` must explicitly mention every relevant one by absolute path unless a file is clearly irrelevant metadata.

If there are more than 12 visible non-placeholder files, related files may be grouped by directory or function, but every relevant file must still be covered by a clear role in the task contract.

Do not mention `.gitkeep` placeholders, hidden validation files, Dockerfiles, build scripts, caches, Python bytecode, generated tests, previous solutions, or benchmark machinery.

`solution_hint` and `test_hint` must preserve the same file-role understanding so later stages do not need to rediscover it.

REQUIREMENTS FOR `instruction_md`:

`instruction_md` must be the final user-facing task instruction.

It must open with the main objective immediately, use natural Markdown prose, define exact final output paths and formats, define required sections/keys/columns/tables/records/assets/components, state source-to-output derivations, state required ordering or completeness when relevant, state explicit exclusions, and make relationships between multiple artifacts explicit.

Avoid vague wording such as "analyze the files", "summarize the data", "integrate everything", or "produce a report" unless paired with concrete output requirements.

`instruction_md` must not include shell commands, command flags, code snippets, implementation recipes, ordered execution steps, validation internals, scoring details, references to hidden tests, references to prompt generation, or references to `solution_hint` or `test_hint`.

Good section names for `instruction_md` may include Objective, Inputs, Required output, Required content, Source-to-output mapping, and Formatting and validation constraints. Use only the sections that improve clarity.

REQUIREMENTS FOR `solution_hint`:

`solution_hint` must be a Markdown-formatted string with exactly these top-level headings, in this order:

## Construction target
## Source roles and extraction plan
## Transformation and ordering plan
## Cross-reference plan
## Formatting plan
## Pitfalls to avoid

`solution_hint` must name every required output artifact using its exact absolute path; list all relevant input files and roles; explain what to extract, copy, summarize, count, group, sort, transform, or cross-reference from each source; explain required ordering; explain how to keep generated artifacts mutually consistent; explain source files that must not be modified; explain negative constraints; and warn about likely mistakes.

`solution_hint` must not include runnable code, shell commands, a completed final artifact, or new output paths or requirements absent from `instruction_md`.

REQUIREMENTS FOR `test_hint`:

`test_hint` must be a Markdown-formatted string with exactly these top-level headings, in this order:

## Validation scope
## Required artifact checks
## Source-derived assertions
## Relationship and consistency checks
## Exclusion and robustness checks
## Likely failure modes

`test_hint` must name every required output artifact using its exact absolute path; state expected file format; identify local source files that tests should inspect at runtime; describe values that should be dynamically derived from source files rather than hard-coded; describe required headings, keys, columns, records, tables, assets, components, count checks, ordering checks, path-reference checks, cross-reference checks, negative checks, and weak or partial solutions to catch.

If exact values are present in the input JSON, include them when stable and useful. If exact values require reading fixture contents not provided in the input JSON, instruct future tests to derive them from real local source files at runtime instead of guessing.

`test_hint` must not contain runnable test code, expose hidden validation internals, mention scoring, or add new output paths or requirements absent from `instruction_md`.

CONSISTENCY RULES ACROSS THE THREE FIELDS:

- Every final output path in `instruction_md` must also appear in `solution_hint` and `test_hint`.
- Every required source file path used by the task must appear consistently across the three fields.
- `solution_hint` must describe how to satisfy the requirements stated in `instruction_md`.
- `test_hint` must describe how to validate the requirements stated in `instruction_md`.
- The hints may clarify emphasis, but they must not add hidden requirements.
- If the hints are more detailed than `instruction_md`, that detail must be a natural consequence of the instruction, not a new task.
- All three fields must use the same absolute `/task_file`-rooted paths.
- All three fields must be grounded only in the input JSON and visible local files.

SELF-CHECK BEFORE RETURNING:

Before returning, ensure the output is valid JSON; the output JSON has exactly three keys: `instruction_md`, `solution_hint`, and `test_hint`; every relevant visible file is accounted for; every required output has exactly one explicit absolute path; the same required output paths appear in all three fields; `instruction_md` is user-facing and does not mention tests, hints, hidden validation, or benchmark machinery; `solution_hint` and `test_hint` are aligned with `instruction_md`; no field invents missing files, missing outputs, external dependencies, or live service requirements.

Return one valid JSON object and nothing else.

Return this JSON schema exactly:

{{
  "instruction_md": "final valid Markdown instruction",
  "solution_hint": "Markdown construction plan for downstream solution generation",
  "test_hint": "Markdown validation plan for downstream test generation"
}}

INPUT JSON:
{input_json}
"""


REVERSE_SOLUTION_USER_PROMPT = """You are generating the reference solution artifacts for a terminal benchmark task.

Your job is to write:
1. `solution/solve.sh`
2. a small set of intentionally incomplete partial solution scripts

PRIMARY OBJECTIVE:

Generate a deterministic reference solution that is maximally likely to pass the provided `generated_test_state` while remaining faithful to `instruction_md` and `solution_hint`.

The generated `solution_sh` must create the final observable state that the pytest verifier expects. During generation, you must treat `generated_test_state` as executable validation evidence. At runtime, `solution_sh` must never read tests, validation logs, hidden files, benchmark internals, previous solutions, pipeline artifacts, or `generated_test_state`.

INPUT PROVIDED:

1. `instruction_md`
   - The final user-facing task contract.
   - It defines the intended task, required outputs, exact paths, formats, schemas, headings, sections, columns, ordering, source-to-output mappings, and explicit exclusions.

2. `solution_hint`
   - The canonical construction plan generated during the instruction stage.
   - It explains intended source roles, extraction plan, transformations, grouping, sorting, cross-references, formatting, and known pitfalls.
   - It is not optional background. Follow it closely whenever it is consistent with `instruction_md` and `generated_test_state`.

3. `selected_fixture_summaries`
   - Structure summaries and selected previews of visible local fixtures.
   - Use these previews to understand likely fixture shape, field names, stable IDs, record counts, statuses, and source relationships.
   - Treat previews as incomplete generation-time context. Runtime code must parse the real local files.
   - Do not hard-code source-derived values solely because they appear in a preview unless the runtime script also reads the fixture containing that value.

4. `generated_dockerfile`
   - Environment context.
   - Use it to determine installed Ubuntu packages, Python packages, CLI tools, fonts, and runtimes.
   - If unavailable or unclear, prefer Bash plus Python standard library.

5. `generated_test_state`
   - The generated pytest verifier file for this task.
   - This is the concrete validation contract for this solution-generation step.
   - Use it to align exact output paths, schemas, headings, key order, source-derived values, helper parsing logic, fallback logic, regexes, accepted formats, and edge cases.
   - Do not make runtime `solution_sh` read this file or any tests directory.

6. Optional fields, if present:
   - `real_env_file_summary`: runtime-visible files and directories under the task root.
   - `expected_output_contract`: machine-readable output path checklist.
   - `environment_metadata`: output directories and build readiness metadata.
   - `constraints`: task root, base image, prompt metadata.

CORE PRIORITY ORDER:

Use this precedence for observable final artifacts:

1. Safety and hard runtime boundaries.
2. Concrete assertions in `generated_test_state`.
3. `instruction_md`.
4. `solution_hint`.
5. Runtime fixture contents.
6. `selected_fixture_summaries`.
7. Optional environment summaries and output contracts.

More specifically:
- If `generated_test_state` asserts a concrete path, key, heading, order, filename pattern, derived value, fallback rule, or schema shape, produce output that satisfies that assertion.
- If `generated_test_state` and `instruction_md` differ in a harmless way, prefer `generated_test_state` because the reference solution must pass the generated verifier.
- If `generated_test_state` clearly contradicts a safety rule or requires reading hidden/tests/runtime-internal files, do not violate the safety rule. Satisfy all compatible assertions.
- If `instruction_md` is precise and `generated_test_state` is silent, follow `instruction_md`.
- If `solution_hint` is more specific than `instruction_md` and does not conflict with `generated_test_state`, follow `solution_hint`.
- If `selected_fixture_summaries` reveal fixture shape that differs from the instruction wording, write runtime extraction code that handles the actual shape while still producing the required output schema.
- Do not add deliverables, sections, top-level keys, columns, or output paths that are absent from `instruction_md`, `solution_hint`, `generated_test_state`, or expected output contract.

MANDATORY VERIFIER-FIRST REASONING:

Before writing `solution_sh`, privately build a test-satisfaction matrix from `generated_test_state`. Do not output this matrix.

The matrix must include, for every pytest function:
- test function name;
- required output paths it opens or checks;
- required imports or file formats implied by the test;
- exact top-level keys and key order;
- exact nested keys;
- expected values hard-coded in the test;
- values derived from runtime fixtures and the exact derivation logic;
- regexes used by the test;
- fallback logic used by the test;
- path root checks;
- non-empty checks;
- manifest/list length checks;
- image/document magic byte checks;
- metadata preservation checks;
- negative-string checks;
- input-preservation checks.

Then ensure `solution_sh` creates outputs satisfying each row of the matrix.

If the test derives expected values from fixture files, mirror the test's derivation logic exactly when safe. For example:
- If the test looks for a case-sensitive cookie key named `user-id`, do not substitute `user_id` unless the test also accepts it.
- If the test checks `normalized_body` before `requestPreview`, use the same fallback order.
- If the test expects the first record in an array rather than the numerically cheapest record, use the first record.
- If the test computes a boolean from actual fixture evidence and the result is false, output false. Do not force a success state.
- If the test checks exact top-level key order, construct JSON in that order.
- If the test checks headings by exact string, use those exact strings.
- If the test extracts version strings using a regex, produce the value that regex would derive.
- If the test allows only a specific URL or path field, preserve that exact allowed value and redact other forbidden values.

Do not merely satisfy the instruction at a high level. Satisfy the verifier's observable assertions.

RUNTIME BOUNDARIES:

Runtime `solution_sh` must not:
- read `tests/`;
- read `solution/`;
- read validation logs;
- read hidden files;
- read pipeline artifacts;
- read `generated_test_state`;
- call live APIs;
- authenticate;
- use private credentials;
- depend on current time;
- depend on random values;
- depend on network state;
- use browser automation;
- start long-running services.

Runtime `solution_sh` may:
- read visible task input files under the task root;
- write required output artifacts;
- use installed local tools from the Dockerfile;
- use Python standard library;
- use already-installed public Python packages;
- install a missing public dependency only when genuinely necessary and not forbidden.

TASK ROOT AND PATH RULES:

- Infer task root from `constraints.task_root`, else from absolute paths in `instruction_md`, `solution_hint`, `generated_test_state`, or fixture summaries, else default to `/task_file`.
- `solution_sh` must start with:
  - `#!/bin/bash`
  - `set -e`
  - `cd <task_root>`
- All final output paths must be absolute and rooted under the task root unless an output file explicitly requires relative paths inside its content.
- Create all required parent directories before writing outputs.
- Normalize duplicate paths such as `/task_file/output` and `/task_file/output/`.
- Classify every output path from `instruction_md`, `solution_hint`, `generated_test_state`, and `expected_output_contract` as:
  - exact file,
  - exact directory,
  - naming prefix,
  - glob/pattern,
  - ambiguous placeholder.
- Exact files must be created as files.
- Exact directories must be created as directories.
- Prefix-like or pattern-like paths must not be created as literal files unless explicitly required.
- Examples of non-literal paths include paths ending in an underscore, paths containing angle-bracket placeholders, wildcard-like text, or paths described as naming conventions.
- For pattern outputs such as slide images, derive concrete files from fixture counts, instruction wording, and verifier checks.
- Remove stale generated files from previous runs when they could break exact count, manifest, or directory-listing assertions.
- Do not treat input fixture files as output targets unless in-place modification is explicitly required.
- If input files must remain unmodified, preserve them and do not rewrite them.

CORE RULES FOR `solution_sh`:

- The script must create every required final artifact at the exact expected path.
- The script must parse real local input files at runtime.
- The script must derive source-dependent values from local fixtures, not from previews alone.
- The script must be deterministic and idempotent.
- Prefer one embedded Python program using `python3 - <<'PY'` for all nontrivial parsing, transformation, output generation, sanitization, and self-checks.
- Bash should mainly set strict mode, `cd`, create directories, optionally verify tools, and invoke Python.
- Use Python serializers such as `json.dumps`, `csv`, XML/ZIP libraries, and pathlib operations rather than fragile shell text substitution.
- Use `ensure_ascii=False` for JSON containing non-ASCII text.
- Preserve meaningful source order unless instruction or verifier requires sorting.
- Avoid `sed` replacement for arbitrary content.
- Avoid dynamically generating Python source code.
- Do not pipe Python dict/list repr strings into `json.loads`.
- Every Python helper and imported module must be defined/imported before use.

MANDATORY SAFE PYTHON HELPER PATTERN:

For nontrivial embedded Python, include small safe helpers and use them consistently:

- `as_dict(value)`: returns value if it is a dict, otherwise an empty dict.
- `as_list(value)`: returns value if it is a list, otherwise an empty list.
- `as_str(value)`: returns value if it is a string, empty string for None, otherwise string conversion for safe scalars.
- `deep_get(obj, path, default=None)`: safely walks nested dict/list paths without raising KeyError, TypeError, or IndexError.
- `first_non_empty(*values, default="")`: returns the first non-empty value.
- `read_json(path)`: reads JSON and gives a clear error for missing or invalid required files.
- `write_json(path, data)`: writes UTF-8 JSON with stable indentation.
- `walk_json(obj)`: recursively yields key paths and values.
- `find_candidate_list(obj, names)`: recursively finds a list under likely semantic keys.
- `safe_number(value, default=None)`: returns numeric values as numbers, not strings.
- `safe_bool_from_status(status, healthy_values)`: computes booleans from actual status strings.

Hard safety:
- Never index a dict with a possibly missing or None key.
- Never call `.get` on a value unless it is known to be a dict or wrapped with `as_dict`.
- Never iterate a candidate collection unless it is known to be a list or wrapped with `as_list`.
- Never assume a field such as `topics`, `items`, `records`, `results`, `documents`, `entries`, `data`, `payload`, `request_body`, `status`, `id`, `url`, or `name` exists at a fixed level unless the verifier or instruction explicitly requires that level.
- If a field may be absent or represented in multiple shapes, write tolerant extraction code while emitting the exact required output schema.
- If the verifier uses a specific exact key or exact case-sensitive field, mirror that exactness.

GENERATED_TEST_STATE ALIGNMENT RULES:

During generation:
- Read `generated_test_state.content` from the input JSON.
- Extract all concrete assertions.
- Extract all fixture-derived calculations.
- Extract every expected output path and every input path the tests use.
- Extract exact key order from lists used in assertions.
- Extract exact heading strings.
- Extract expected counts and how they are computed.
- Extract accepted extensions and magic bytes.
- Extract whether tests compare sorted lists, list order, set equality, or exact object equality.
- Extract whether tests allow fallback values.
- Extract whether tests reject placeholders or external URLs.

When writing `solution_sh`:
- Reproduce the verifier's fixture-derived logic in runtime code.
- Make output types match exactly: booleans must be booleans, numbers numbers, arrays lists, objects dicts, strings strings.
- If the test validates only structure for a complex artifact, create the simplest meaningful valid artifact satisfying that structure.
- If the test checks a value by exact equality, produce that exact value.
- If the test checks inclusion, include the required value without adding risky extra top-level fields.
- If the test checks no extra keys, emit exactly the allowed keys.
- If the test checks list order, emit that order.
- If the test checks a path is absolute and under task root, emit absolute task-rooted paths.
- If the test checks a manifest path exists, create that file before writing or finalizing the manifest.
- If the test checks original metadata entries are unchanged, deep-copy them unchanged and append new entries.
- If the test checks top-level counters, recompute counters after all mutations.
- If the test checks input files still exist, do not delete, move, truncate, or rewrite them.

Do not implement self-checks that are stricter than `generated_test_state` unless the instruction explicitly requires them and they cannot cause a compliant verifier-aligned output to fail.

SELF-CHECK PHILOSOPHY:

Self-checks inside `solution_sh` should improve pass rate, not cause false failures.

Required behavior:
- Generate outputs first.
- Sanitize and repair outputs.
- Re-read outputs.
- Validate only required paths, parseability, schema, key order, counts, cross-file consistency, and explicit negative constraints.
- If a self-check detects a repairable issue, repair it and re-check.
- Exit nonzero only when a required input is missing/unparseable, a required output cannot be created, or a non-repairable invariant remains after repair.
- Do not force desired success booleans. Verify consistency with actual fixture-derived booleans.
- Do not fail because optional arrays are empty unless the verifier or instruction explicitly requires non-empty arrays.
- Do not fail because a fixture contains failure/degraded/disabled/unhealthy states. Reflect those states in output when required.
- Do not reject sentinel values such as `unknown`, `null`, `false`, empty arrays, or empty strings when the verifier or instruction allows them.
- Avoid generic placeholder scans over entire files. Scope placeholder checks to generated IDs, URLs, names, required explanations, and fields that must contain real values.

DEPENDENCY AND TOOL RULES:

- Prefer Python standard library.
- Inspect `generated_dockerfile.content` before using non-standard modules or CLI tools.
- If a Python package or CLI tool is already installed, use it directly and do not reinstall it.
- If a non-standard dependency is not installed and the task can be solved with the standard library, do not install it.
- If installation is genuinely necessary and not forbidden, install minimally and non-interactively.
- Avoid runtime package installation when the instruction forbids network, package manager side effects, or external access.
- Do not use exact package version pins unless the input explicitly provides a verified available version.
- Do not use private indexes, direct URLs, git packages, local paths, browser drivers, GPU packages, credentials, or services.
- Do not import a non-standard module at top level before checking or installing it when needed.

Known import/package mapping:
- import name `yaml` corresponds to PyPI package `pyyaml`.
- import name `PIL` corresponds to PyPI package `Pillow`.
- import name `pptx` corresponds to PyPI package `python-pptx`.
- import name `openpyxl` corresponds to PyPI package `openpyxl`.
- import name `bs4` corresponds to PyPI package `beautifulsoup4`.
- import name `fitz` corresponds to PyPI package `PyMuPDF`.

YAML-specific:
- Avoid YAML dependencies when possible.
- If YAML input is simple, use a small standard-library parser for straightforward key-value/list structures.
- If full YAML is genuinely required and PyYAML is not installed, install `pyyaml` before importing `yaml`, unless installation is forbidden.
- Never allow `ModuleNotFoundError: yaml` to make `solve.sh` fail when a standard-library fallback is practical.

JSON OUTPUT RULES:

- Emit valid RFC 8259 JSON encoded in UTF-8.
- Use `json.dumps`.
- Preserve top-level key order when verifier or instruction checks it.
- Emit exactly the required top-level keys when no extras are allowed.
- Use correct JSON types.
- Keep counters consistent with associated arrays.
- If extending an input JSON snapshot:
  - deep-copy original entries unchanged;
  - identify stable IDs such as `doc_id`, `id`, `path`, `url`, or `name`;
  - preserve original entry objects exactly unless modification is explicitly required;
  - append new entries deterministically;
  - recompute top-level counters only when they logically represent list length or the verifier expects it;
  - preserve unrelated top-level metadata unless the verifier permits/needs a change.

MARKDOWN OUTPUT RULES:

- Emit a top-level heading unless forbidden.
- Include exact required headings in exact order.
- If the verifier checks level-2 headings, do not add extra level-2 headings.
- Include required metadata labels exactly.
- For local file URLs, use `file://` URLs pointing to the expected output path when required.
- For verbatim sections, read the source file and copy its exact text inside a fenced code block.
- Do not sanitize or rewrite verbatim content if the verifier checks exact source preservation, unless a higher-priority safety rule requires redaction.
- For required tables, include exact column labels and required rows.
- Do not embed images unless explicitly required.
- Avoid placeholder prose when real fixture-derived values exist.

CSV AND TSV OUTPUT RULES:

- Use Python `csv`.
- Emit exact headers and order when required.
- Preserve row order unless sorting is required.
- Use strings only where strings are expected and numbers only where numbers are expected if parsed as JSON elsewhere.

DOCUMENT, PPTX, PDF, AND IMAGE RULES:

For PPTX:
- If `python-pptx` is installed, use it for PPTX generation when helpful.
- Prefer using the provided template as the starting presentation when instruction requires applying a template.
- Preserve slide count and slide order from the runtime presentation spec.
- Include representative slide titles/content that the verifier may inspect.
- Ensure the final PPTX is a valid ZIP/OPC package with `[Content_Types].xml`, `ppt/presentation.xml`, and `ppt/slides/slide*.xml`.
- If exact visual fidelity is not tested, prioritize verifier-visible correctness: valid package, slide count, slide order, titles, text, and non-empty file.
- If applying the template fails but the verifier only checks valid PPTX structure and slide content, create a valid PPTX satisfying the verifier rather than exiting.

For slide images:
- If rendered slide images are required, create exactly one image per slide.
- Use allowed formats from instruction or verifier.
- Prefer real local rendering if installed tools make it reliable.
- If real rendering is unavailable or fragile, and the verifier only checks path, count, extension, non-empty size, and magic bytes, create deterministic valid images with slide index/title text using installed Pillow or standard SVG text.
- Write images directly into the required output directory if required.
- Build the manifest from the actual generated paths.
- Ensure manifest image paths are absolute, ordered by slide index, unique, and each file exists.
- Validate image headers before finalizing:
  - PNG standard signature;
  - JPEG standard signature;
  - WebP RIFF/WEBP;
  - SVG text containing an svg element.

For PDF:
- Produce a valid PDF header when PDF is required.
- Do not rely on live rendering or external services.
- Avoid exact pagination assumptions unless verifier checks them.

For DOCX/XLSX:
- Use ZIP/XML or installed libraries.
- Ensure valid package structure.
- Prioritize verifier-visible content and structure over brittle styling.

NEGATIVE CONSTRAINT AND SANITIZATION RULES:

- Enforce explicit negative constraints from `instruction_md` and `generated_test_state`.
- Do not copy forbidden external URLs, network references, base64, embedded images, credentials, backup-file content, or placeholder text unless explicitly allowed or verifier-required.
- Build an allowlist of permitted URLs and URL-like strings from:
  - exact output fields required by instruction;
  - exact fields checked by generated tests;
  - explicit examples of allowed extracted URLs;
  - local `file://` URLs required by the task.
- External URLs not on the allowlist must be redacted or replaced with non-URL descriptions.
- Local file paths and `file://` URLs are not external URLs.
- If the verifier checks exact source text in a verbatim section, do not redact that section unless required by a higher-priority safety constraint.
- For JSON outputs, recursively sanitize string values by key path.
- For Markdown/text outputs, sanitize only non-verbatim generated prose unless global redaction is explicitly required.
- After sanitization, recompute counters, booleans, totals, and failed-check arrays.
- Re-read sanitized artifacts and validate them.

BOOLEAN, STATUS, AND READINESS RULES:

- Do not assume final readiness or validity should be true.
- Compute booleans from actual runtime fixture evidence exactly as instruction or verifier defines.
- Healthy/success values should be matched case-insensitively only when the verifier or instruction does so.
- If a fixture contains degraded, unhealthy, disabled, failed, cancelled, deleted, stale, missing, null, or invalid states, reflect them in output when required.
- Aggregate booleans must be consistent with component booleans.
- Failed-check arrays must match failed components.
- Exit-code-equivalent fields must match the specified boolean logic, not the actual shell exit code unless explicitly required.
- Self-checks should verify consistency, not force success.

FIXTURE-SHAPE ROBUSTNESS:

- Treat fixture summaries as previews, not complete schemas.
- Runtime code must parse actual files.
- Use recursive discovery only when the verifier or instruction permits flexible shape.
- If the verifier expects a specific key path, use that path exactly.
- If the instruction says exact case-sensitive field matching, do not silently alias near-matches.
- If a near-alias exists but exact field is absent, output the exact-field-derived result, even if false or empty.
- For topic/catalog/trending tasks, do not assume a top-level `topics` array unless the verifier or fixture summary confirms it. Search candidate arrays when allowed.
- For request-body tasks, check the same candidate containers and order used by the verifier.
- For inventory/state tasks, preserve schema and compute validity from actual records. Do not mark invalid merely because optional fields are absent or null unless verifier does.
- For port/log tasks, prefer explicit labels in the fixture, such as unknown, failed, resolved, external, healthy, unhealthy, deleted, cancelled, valid, or invalid, over broad external knowledge.

COMMON VERIFIER-PASSING RECIPES:

For a single JSON manifest:
- Create exactly the tested top-level keys in the tested order.
- Parse every source fixture the tests parse.
- Mirror the tests' derivation logic for each field.
- Emit exact paths as absolute strings.
- Compute aggregate booleans from component values.
- Do not add extra keys if tests reject them.

For Markdown plus metadata:
- Generate the Markdown first.
- Extract or assign deterministic synthetic IDs.
- Use the same ID and local file URL in metadata.
- Generate manifest files next.
- Update metadata by preserving original entries exactly and appending new entries.
- Recompute counters.

For presentation plus images:
- Parse slide spec.
- Derive slide count from the same source the tests use.
- Create PPTX with exactly that slide count and titles/text in order.
- Create one image per slide.
- Write manifest with exact schema and ordered absolute image paths.
- Update downstream metadata using manifest paths.

For negative URL constraints:
- Preserve only verifier-required extracted URLs and required local file URLs.
- Redact all other external URLs.
- Never redact values that tests compare exactly unless safety requires it.

RUNTIME SELF-CHECK REQUIREMENTS:

Include lightweight final checks in `solution_sh`:
- Required output paths exist and are non-empty.
- JSON outputs parse.
- Exact top-level keys and key order are correct when required.
- Markdown headings and required labels are present.
- Verbatim source sections match when required.
- Manifest-listed files exist.
- Binary artifacts have valid magic/ZIP headers when relevant.
- Counts and aggregate booleans are consistent.
- Original input files still exist when they must not be modified.
- Forbidden strings are absent except allowlisted values.
- Existing metadata entries are preserved unchanged when required.

Self-checks must be implemented with Python standard library whenever possible and must not invoke pytest.

DEPENDENCY FAILURE AVOIDANCE:

- Prefer not to install anything.
- Prefer not to use non-standard Python modules unless Dockerfile clearly installs them.
- If `generated_dockerfile` installs a package, use it without reinstalling.
- If a tool such as LibreOffice is listed but may be fragile, include a fallback that still creates verifier-valid outputs.
- If a module import might fail, guard it with `importlib.util.find_spec` or use fallback logic.
- Never let optional rendering, optional styling, optional OCR, optional network, or optional package installation prevent creation of structurally valid verifier-expected outputs.

PARTIAL SOLUTION RULES:

Generate 1 to 3 executable partial scripts.

Each partial must:
- start with `#!/bin/bash`;
- include `set -e`;
- `cd` into the task root;
- be deterministic;
- usually exit 0;
- create at least one plausible but incomplete artifact;
- fail robust validation because final observable state is missing, incomplete, inconsistent, or structurally wrong;
- avoid package installation;
- avoid network;
- avoid authentication;
- avoid reading tests, hidden files, validation logs, or pipeline artifacts.

Good partial failure modes:
- missing one required output file;
- missing one required section;
- wrong key order;
- missing manifest entries;
- wrong count;
- placeholder values;
- no metadata preservation;
- no rendered images;
- copied fixture instead of transformed output;
- aggregate boolean inconsistent with components.

OUTPUT REQUIREMENTS:

Return one valid JSON object and nothing else.

The JSON object must have exactly:
- `solution_sh`: a JSON string containing a complete Bash script.
- `partials`: a JSON array containing 1 to 3 partial solution objects.

`solution_sh` requirements:
- must start exactly with `#!/bin/bash`;
- must include `set -e`;
- must include `cd <task_root>`;
- must not contain Markdown fences;
- must not read tests or hidden artifacts at runtime;
- must generate every required exact output file and directory;
- must handle pattern outputs by creating concrete files, not literal prefix files.

Each partial object must have:
- `name`: a safe filename ending in `.sh`;
- `content`: a complete Bash script starting with `#!/bin/bash`, including `set -e` and `cd <task_root>`.

SELF-CHECK BEFORE RETURNING:

Before returning, privately verify:
- The returned text is valid JSON parseable by `json.loads`.
- `solution_sh` starts with `#!/bin/bash`.
- `solution_sh` includes `set -e`.
- `solution_sh` changes into the task root.
- Runtime code never reads tests, hidden evaluator files, validation logs, solution-generation artifacts, or pipeline artifacts.
- Runtime code does not call live APIs, authenticate, or depend on network state.
- Every helper referenced in embedded Python is defined.
- Every imported module is standard library, installed according to Dockerfile, or installed before import when allowed.
- No bare `import yaml` occurs unless PyYAML is installed or installed first.
- No dict is indexed with a possibly None key.
- No fixture schema is assumed when it may vary, unless the verifier requires that exact schema.
- Every exact output path from the verifier/instruction is created.
- Pattern outputs become concrete files.
- Generated artifacts satisfy each pytest function in the private test-satisfaction matrix.
- Self-checks are not stricter than the verifier in ways that could cause false failure.
- Partial scripts are plausible, incomplete, executable, and safe.

Return this JSON schema exactly:

{{
  "solution_sh": "#!/bin/bash\nset -e\ncd /task_file\n...",
  "partials": [
    {{"name": "partial_solve_missing_section.sh", "content": "#!/bin/bash\nset -e\ncd /task_file\n..."}}
  ]
}}

INPUT JSON:
{input_json}
"""


REVERSE_TEST_USER_PROMPT = """You are a senior Python engineer who writes robust pytest suites for terminal-agent benchmarks.

You are generating state-based tests for a task after the instruction-stage planning bundle has been produced.

The tests must validate the final observable filesystem state after an agent completes the task. They must not depend on implementation details of the reference solution.

The `test_hint` is not optional background. It is the canonical validation plan generated during the instruction stage. Treat it as the main plan for what to validate, which artifacts matter, which source-derived assertions are important, which relationships must hold, and which common failure modes must be caught.

INPUT PROVIDED:

1. `instruction_md` - the final user-facing task contract and authoritative source for required outputs, exact paths, formats, schemas, headings, sections, columns, records, ordering, source-to-output mappings, and explicit exclusions.
2. `test_hint` - the canonical validation plan. Follow it closely whenever consistent with `instruction_md`.
3. `selected_fixture_summaries` - structure summaries and selected previews of visible local text fixtures. Use them to understand likely runtime fixture schemas, stable IDs, counts, field names, statuses, and source relationships. Do not treat previews as complete files; tests must parse real fixture files at runtime.
4. `generated_dockerfile` - optional environment context for installed verifier-side tools and libraries. Prefer Python standard library if unavailable or unclear.

CORE GOAL:

Generate state-based pytest tests that validate the final observable state required by `instruction_md`, following the validation plan in `test_hint`.

The tests must be plan-driven: use `instruction_md` as the final contract, `test_hint` as the mandatory validation plan, `selected_fixture_summaries` to understand real fixture schemas and examples, and only source paths explicitly named in `instruction_md`, `test_hint`, or `selected_fixture_summaries`. Do not rely on any separate environment-summary field. Do not read solution files, hidden files, validation logs, benchmark internals, or pipeline artifacts at test runtime.

The tests must fail on an untouched environment, pass on any compliant solution, derive expected values from runtime input fixtures whenever possible, avoid hidden files and live services, and cover the validation focus described in `test_hint` when supported by `instruction_md`.

PLAN PRECEDENCE:

- `instruction_md` is the final contract.
- `test_hint` is the canonical validation plan for that contract.
- If `test_hint` is more specific than `instruction_md` and does not contradict it, follow `test_hint`.
- If they conflict, follow `instruction_md` while preserving as much validation intent as possible.
- Use `selected_fixture_summaries` only to identify likely source fixture shapes and deterministic runtime derivations; do not hard-code preview-only values when tests can parse real source files.
- Do not add a required output path, section, key, column, record, transformation, or exclusion absent from `instruction_md`.

PRIVATE VALIDATION PLAN EXTRACTION:

Before writing tests, privately derive a validation plan from `instruction_md` and `test_hint`. Include task root, exact outputs, output directories, patterns, in-place targets, input source paths and roles, source-derived assertions, schemas, key order, headings, tables, records, row counts, manifest rules, cross-file consistency, ordering, path-reference checks, negative constraints, and likely failure modes.

TEST STRATEGY:

- Prefer assertions about required output existence, non-empty content, file format, parseability, paths, schema shape, required sections, required records, and cross-file consistency.
- Tests must be nop-safe.
- Generate 4 to 8 meaningful pytest functions total when practical and cover every required output artifact at least once.
- For each major item in `test_hint`, include at least one assertion when supported by `instruction_md`.
- For JSON, CSV/TSV, Markdown, binary documents, in-place modifications, manifests, images, and metadata updates, test robust structural properties and source-derived values without brittle implementation-specific checks.
- Test that outputs are not empty placeholders or simple copies when consolidation, filtering, normalization, rendering, merging, or audit synthesis is required.
- Do not fail solely because harmless extra files exist unless exact directory listing is required.

PATH, DERIVATION, AND RELATIONSHIP RULES:

Normalize duplicate paths. Classify output paths as exact file, exact directory, pattern/prefix, or ambiguous placeholder. Assert exact files directly, exact directories as directories, and derive concrete expected files for pattern outputs from `instruction_md`, `test_hint`, and runtime fixtures. All asserted paths must be absolute and rooted at task root unless relative paths are explicitly required inside a manifest.

When expected values come from input fixtures, parse them from those fixtures at test runtime rather than hard-coding prompt context. Source fixture paths must come from `instruction_md`, `test_hint`, or `selected_fixture_summaries`. For JSON/JSONL/CSV/text fixtures, derive IDs, counts, statuses, names, labels, ordering, booleans, and representative required entities from the real runtime files. Assert synthetic identifiers only for non-empty, non-placeholder presence and cross-output reuse unless exact values are specified.

Check cross-file relationships explicitly when required: output references to generated artifacts, manifest lists, report summaries of source records, metadata references, shared derived values, source order, and sorting rules.

CONTRACT-SPECIFIC CHECKS:

Use standard-library parsing where possible. For JSON, assert parseability, key sets/order when specified, types, counts, manifest paths, preserved entries, and URL exclusions. For Markdown, validate required headings, metadata blocks, local file URLs, fenced verbatim text when required, tables, and absence of placeholders. For CSV/spreadsheets, validate headers, row counts, source-derived values, and ordering. For PPTX/DOCX/PDF/images, validate existence, non-empty size, package structure, magic bytes, expected counts, and required text where feasible without brittle visual checks.

EXCLUSION AND ROBUSTNESS CHECKS:

Include negative assertions for exclusions emphasized by `instruction_md` or `test_hint`: absence of external URLs, live-service language, credentials, placeholders, base64, embedded media, extra keys, or modified source fixtures when prohibited. Do not inspect solution files, test internals, hidden files, validation logs, build scripts, or pipeline artifacts at runtime. `test_state_py` must not run commands, shell tools, services, live network calls, package managers, or the agent solution. Do not use `subprocess`, `os.system`, `pexpect`, `requests`, `urllib` network calls, database servers, browsers, CLIs, or package managers in `test_state_py`.

DEPENDENCY RULES:

`packages` may include small public PyPI packages for verifier-side parsing or inspection only. Prefer standard library. Every module used in `test_state_py` must be explicitly imported, including `pytest` whenever any `pytest.*` API or decorator is used. Third-party libraries must be installed by `generated_dockerfile` or listed in `packages`. Do not use exact `==` pins; prefer unpinned public package names. Avoid private indexes, URLs, git packages, local paths, browser drivers, large ML/GPU packages, credentials, or running services. Prefer `[]` when standard library checks are sufficient.

SELF-CHECK BEFORE RETURNING:

Ensure `test_state_py` starts exactly with the required canary line, passes `ast.parse`, defines every helper it references, imports every referenced module, includes `import pytest` when needed, has no forbidden runtime calls, covers every required output artifact, covers major `test_hint` items supported by `instruction_md`, fails untouched environments, passes compliant states without current time/randomness/network/hidden files, derives expected fixture values from runtime files, and does not introduce requirements absent from `instruction_md`.

OUTPUT REQUIREMENTS:

Return one valid JSON object and nothing else. `packages` must be a JSON array of public PyPI package strings beyond pytest and pytest-json-ctrf. `test_state_py` must be a JSON string containing the complete Python pytest file with escaped newlines and must start exactly with:
`# HARBOR_CANARY: tests generated by FACET-Terminal`

Return this JSON schema exactly:

{{
  "packages": [],
  "test_state_py": "# HARBOR_CANARY: tests generated by FACET-Terminal\\nfrom pathlib import Path\\n..."
}}

INPUT JSON:
{input_json}
"""


def render_reverse_prompt(template: str, context: dict[str, Any], *, task_root: str, base_image: str) -> str:
    rendered = template.replace("__TASK_ROOT__", task_root).replace("__BASE_IMAGE__", base_image)
    return rendered.format(input_json=json.dumps(context, ensure_ascii=False, indent=2))
