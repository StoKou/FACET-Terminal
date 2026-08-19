<div align="center">

[简体中文](README.md) | [English](README_EN.md)

<img src="docs/figures/facet-banner.png" alt="FACET: Preserving Source Intent and Executable State in Terminal Task Synthesis" width="100%">

<p>
  <img src="https://img.shields.io/badge/Task-Terminal_Task_Synthesis-2D8BC3" alt="Task">
  <img src="https://img.shields.io/badge/Framework-FACET-5AAFE0" alt="Framework">
  <img src="https://img.shields.io/badge/Python-3.11--3.13-3776AB" alt="Python">
  <img src="https://img.shields.io/badge/License-Apache--2.0-7AAED1" alt="License">
</p>

[[🌐 Project Page](https://stokou.github.io/FACET-Terminal/)]
[[📖 Paper (Coming Soon)](#)]
[[🤗 Data (Coming Soon)](#)]
[[🤗 Models (Coming Soon)](#)]

</div>

---

# 🔥 News

- **`2026-08-19`**: Released the FACET-Terminal task-synthesis code preview and project page.
- **Coming Soon**: Paper, datasets, training configurations, and model checkpoints.

# 💡 FACET

**FACET** (Fine-grained Agentic Construction of Executable Tasks) synthesizes complex, coherent, and verifiable terminal tasks from related agent skills.

It is built around two principles:

- **Preserve source intent** across multi-stage generation, including capabilities, dependencies, I/O contracts, and procedural knowledge.
- **Share executable state** by realizing the environment first and grounding the instruction, solution, and verifier in the same container state.

![FACET Pipeline](docs/figures/facet-pipeline.png)

# ✨ Highlights

- 🧩 **Scenario reconstruction** recovers goals, context, capability relations, intermediate states, and tool constraints.
- 🖥️ **Environment-first construction** realizes and validates the Docker environment before final task generation.
- 🔗 **State alignment** grounds the instruction, reference solution, and verifier in shared initial and final states.
- 🛠️ **Targeted repair** uses failure traces to update only the responsible task artifact.
- 🔬 **Three generation strategies** provide `FORWARD`, `REVERSE`, and `JOINT` for controlled comparisons.

# 📊 Results

Starting from **71,341** source skills, FACET constructs **7,852** scenario-skill seeds and produces **6,078** execution-validated tasks. We further select **1.2K** complete successful trajectories for supervised fine-tuning of the Qwen3.5 model family.

## Terminal-Bench 2.1

All models below use the `Terminus-2` agent. Base and FACET models are evaluated under the same inference configuration, with three independent attempts per task and the mean pass rate reported.

| Model | Size | Base | FACET-Terminal | Absolute Gain |
|:--|--:|--:|--:|--:|
| Qwen3.5-4B | 4B | 17.60 | **24.72** | **+7.12** |
| Qwen3.5-9B | 9B | 27.34 | **35.58** | **+8.24** |
| Qwen3.5-27B | 27B | 40.82 | **47.57** | **+6.75** |

Only 1.2K successful trajectories yield consistent gains across all three scales. The 9B model obtains the largest absolute gain, while the 4B model improves by **40.5%** relatively. FACET-Terminal-Qwen3.5-27B reaches **47.57**, only 1.49 points below Qwen3.5-397B at **49.06** under the same setting, despite being roughly 15 times smaller.

> These are pre-release paper results. Models on public leaderboards may use different agents, inference budgets, or evaluation settings and should not be compared directly with this table.

## Comparison with Existing Terminal Datasets

All trajectory collection and task evaluation use `Terminus-2`. `Tests` denotes the average number of executable checkpoints per task, and P@k denotes pass@k in percent.

| Dataset | # Traj. | Turns | # Tasks | Tests | P@1 | P@3 |
|:--|--:|--:|--:|--:|--:|--:|
| Nemotron-Terminal | 5K | 6.12 | 15K | 6.18 | 40.67 | 48.00 |
| Endless-Terminals | 200 | 4.53 | 2,492 | 5.51 | 83.00 | 87.00 |
| Terminal-Lego | 32K | 5.77 | 15K | 16.60 | 47.00 | 49.00 |
| TerminalWorld | 200 | **11.94** | 1,530 | 3.98 | 57.00 | 82.00 |
| Tmax | 500 | 11.14 | 15K | 3.29 | 80.00 | 86.00 |
| **FACET (Ours)** | **1.2K** | 11.86 | **6,078** | **22.77** | 27.00 | 35.00 |

FACET combines long interaction horizons with the densest executable verification, averaging **22.77** checkpoints per task. Its lower task-level pass rates reflect strict conjunctive success criteria: an agent must satisfy the primary workflow, secondary artifacts, content constraints, and cross-artifact consistency simultaneously.

## Task-Construction Funnel

| Stage | Count | Stage Retention |
|:--|--:|--:|
| Scenario-skill seeds | 7,852 | — |
| Seeds with first-build logs | 7,841 | 99.86% |
| Initial environment success | 6,630 | 84.56% |
| Successful environments after repair | 7,504 | 95.70% |
| Entering task validation | 7,446 | 99.23% |
| First-pass valid tasks | 2,856 | 38.35% |
| Final validated tasks | **6,078** | **81.63%** |

## Generation-Order Ablation

We compare three artifact-generation orders on the same 100 semantic paths. Initial validity uses tasks reaching validation as the denominator; final yield uses all 100 selected paths.

| Strategy | Generation Order | Reached Validation | Initially Valid | Final Yield |
|:--|:--|--:|--:|--:|
| **Forward (Ours)** | Instruction → Solution → Verifier | 99 | **46 (46.5%)** | **83/100** |
| Reverse | Instruction → Verifier → Solution | 91 | 22 (24.2%) | 63/100 |
| Joint | All artifacts in one call | 96 | 36 (37.5%) | 65/100 |

Forward lets the verifier observe the generated reference solution, improving contract alignment among instructions, execution behavior, and checks. Forward allows up to five repair rounds, whereas Reverse and Joint allow three; final yield therefore characterizes the complete pipeline configurations rather than isolated repair efficiency under an identical budget.

# 🔍 Data and Task Analysis

- **Skill coverage:** 71,341 source skills span AI and agents, software and systems, data analysis, document workflows, and multimedia creation.
- **Long-horizon interaction:** successful training trajectories average 11.86 turns, and 95.6% begin with an observation-only step.
- **Strict verification:** teacher rollouts pass 89.40% of individual checks, while only 20.94% achieve complete task success, indicating that many failures miss only a subset of constraints.
- **Near-success failures:** 54.00% of unsuccessful rollouts fail only one or two verifier checks, allowing dense verification to distinguish near-complete trajectories from total failures.

# 📦 Installation

## Requirements

- Python `3.11–3.13`
- [uv](https://docs.astral.sh/uv/)
- Docker for environment construction and executable validation

```bash
git clone https://github.com/StoKou/FACET-Terminal.git
cd FACET-Terminal/facet
uv sync
```

# 🚀 Quick Start

Public configs never store real credentials. Export the model key first:

```bash
export FACET_API_KEY="your-api-key"
```

All configurations, scripts, and Python sources live under `facet/`. From that directory, set your private `api_base`, `model_name`, and input JSONL path in `configs/FORWARD.yaml`, then run:

```bash
uv run python facet_terminal/pipeline.py \
  --config configs/FORWARD.yaml \
  --strategy FORWARD
```

Run one stage:

```bash
uv run python facet_terminal/pipeline.py \
  --config configs/FORWARD.yaml \
  --strategy FORWARD \
  --stage planning
```

Experimental strategies:

```bash
uv run python facet_terminal/pipeline.py --config configs/REVERSE.yaml --strategy REVERSE
uv run python facet_terminal/pipeline.py --config configs/JOINT.yaml --strategy JOINT
```

# 📄 Input Format

The default adapter expects one skill pair per JSONL record:

```json
{
  "pair_id": "pair_demo",
  "skill_ids": ["skill_a", "skill_b"],
  "skill_summaries": ["summary a", "summary b"],
  "scenario_texts": ["initial context", "desired outcome"],
  "quality": {"overall_status": "ACCEPTED"}
}
```

`skill_objects_jsonl` and `mapped_jsonl` adapters are also included for object-based and arbitrarily nested inputs.

# 🗂️ Repository Layout

```text
FACET-Terminal/
├── README.md               # Default Chinese project documentation
├── README_EN.md            # English project documentation
├── docs/                   # Static GitHub Pages site and paper figures
└── facet/                  # All open-source code, configs, and scripts
    ├── common/             # Config, IO, hashing, model client, and run context
    ├── configs/            # Sanitized configs for three generation strategies
    ├── facet_terminal/
    │   ├── stages/         # Scenario, environment, generation, validation, and repair
    │   ├── harbor-template/ # Harbor task template
    │   ├── pipeline.py     # CLI entrypoint and stage routing
    │   └── prompts*.py     # Default and experimental prompts
    ├── scripts/            # Auxiliary-script notes and extension entrypoints
    ├── tests/              # Unit tests
    ├── .env.example        # Environment-variable template
    ├── pyproject.toml      # Python project and dependency configuration
    └── uv.lock             # Reproducible dependency lockfile
```

# 🔒 Release and Safety Notes

- Source datasets, generated tasks, trajectories, model weights, and runtime outputs are not included.
- API keys are read from `FACET_API_KEY`; `facet/.env*`, `facet/configs/local/`, and runtime directories under `facet/` are ignored.
- The pipeline builds and executes generated Docker tasks. Run it on an isolated development machine or sandbox, not on a production host that contains sensitive data.

# 🧪 Tests

```bash
cd facet
uv run pytest
```

# ✉️ Contact

Questions and feedback are welcome:

📧 **Kou Shi** — [stokou@mail.ustc.edu.cn](mailto:stokou@mail.ustc.edu.cn)

# 📚 Citation

If FACET is useful in your research, please cite:

```bibtex
@misc{shi2026facet,
  title   = {{FACET}: Preserving Source Intent and Executable State in Terminal Task Synthesis},
  author  = {Kou Shi and Zun Wang and Qisheng Su and Shiting Huang and Ziao Zhang and Zhen Fang and Qingnan Ren and Jin Liu and Yu Zeng and Yiming Zhao and Lin Chen and Zehui Chen and Feng Zhao},
  year    = {2026},
  note    = {Preprint},
  url     = {https://github.com/StoKou/FACET-Terminal}
}
```
