# env_build Stage

This stage owns environment construction and environment-only validation.

Inputs:
- `artifacts/facet_terminal/instruction_ref_units.jsonl`
- per-task `pipeline_artifacts/instruction_ref.md` as task-intent reference

Outputs:
- `artifacts/facet_terminal/env_build_units.jsonl`
- per-task `environment/Dockerfile`
- per-task `environment/task_file/**`
- per-task `pipeline_artifacts/environment/env_signals.json`
- per-task `pipeline_artifacts/environment/build_runtime/**` for build logs,
  attempt counters, build metadata, artifact history, and structured env-check
  results
- per-task `pipeline_artifacts/share/real_env_file_summary.json` runtime-visible task file summary
- per-task env build reports under `artifacts/facet_terminal/env_build_reports/`

The stage only gives the model `instruction_ref` plus base-image/task-root
constraints plus the Harbor Dockerfile template. The model returns a complete
Dockerfile, build-context files under `task_file/` and `build_scripts/`, and
environment-only smoke checks. The stage blocks obvious final output files,
requires non-simple fixtures to be generated/downloaded by build scripts or
Dockerfile build steps, auto-adds a
fixture manifest when missing, and records
Buildability/Launchability/FixtureReadiness maturity signals.
Build failures can trigger a bounded repair loop that only allows changes to
the Dockerfile, build-context file patch/delete operations, and smoke checks.
Smoke checks are executed one by one through `tooling/scripts/verify_env_checks.py`
so setup failures include per-check stdout/stderr and simple authenticity
warnings for mock-like command paths.
Raw model/repair Dockerfiles are saved under `pipeline_artifacts/environment/`
as intermediate artifacts. The final `environment/Dockerfile` is canonicalized:
validation-only `RUN test ...`, `RUN command -v ...`, and JSON/CSV parsing
checks are stripped and kept out of the image definition. Those checks belong
only in `env_checks`, which the stage runs after the image is built.

The local `tooling/scripts/` files are sanitized copies of the useful
environment-building helpers. They are kept inside this stage so the public
pipeline does not import external task-generation code at runtime.
