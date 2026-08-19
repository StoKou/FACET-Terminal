<div align="center">

[简体中文](README.md) | [English](README_EN.md)

<img src="docs/figures/facet-banner.png" alt="FACET: Preserving Source Intent and Executable State in Terminal Task Synthesis" width="100%">

<p>
  <img src="https://img.shields.io/badge/Task-Terminal_Task_Synthesis-2D8BC3" alt="Task">
  <img src="https://img.shields.io/badge/Framework-FACET-5AAFE0" alt="Framework">
  <img src="https://img.shields.io/badge/Python-3.11--3.13-3776AB" alt="Python">
  <img src="https://img.shields.io/badge/License-Apache--2.0-7AAED1" alt="License">
</p>

[[🌐 项目主页](https://stokou.github.io/FACET-Terminal/)]
[[📖 论文（即将发布）](#)]
[[🤗 数据（即将发布）](#)]
[[🤗 模型（即将发布）](#)]

</div>

---

# 🔥 动态

- **`2026-08-19`**：发布 FACET-Terminal 任务合成代码预览版与项目主页。
- **Coming Soon**：论文、数据、训练配置和模型权重。

# 💡 FACET

**FACET**（Fine-grained Agentic Construction of Executable Tasks）从相关 Agent Skills 出发，合成复杂、连贯且可执行验证的终端任务。

它围绕两个核心原则设计：

- **保留源意图**：在多阶段生成中持续保留能力、依赖、输入输出约束和过程知识。
- **共享可执行状态**：先构造并修复环境，再让指令、解法和验证器基于同一容器状态完成生成。

![FACET Pipeline](docs/figures/facet-pipeline.png)

# ✨ 核心特性

- 🧩 **场景重建**：从技能对恢复目标、上下文、能力关系、中间状态与工具约束。
- 🖥️ **环境优先**：在最终任务组件生成前实现并验证 Docker 环境。
- 🔗 **状态对齐**：指令、参考解法和验证器共享相同的初始与最终执行状态。
- 🛠️ **定向修复**：根据失败轨迹定位并只修复有问题的任务组件。
- 🔬 **三种生成策略**：提供 `FORWARD`、`REVERSE` 和 `JOINT` 以复现实验对比。

# 📊 实验结果

FACET 从 **71,341** 个来源技能出发，构造 **7,852** 条场景—技能种子，最终得到 **6,078** 个通过执行验证的任务。我们进一步从成功 rollout 中筛选 **1.2K** 条完整轨迹，用于监督微调 Qwen3.5 系列模型。

## Terminal-Bench 2.1

所有下列模型均使用 `Terminus-2` Agent。基础模型与 FACET 模型在相同推理配置下评测，每个任务独立运行三次并报告平均通过率。

| 模型 | 参数量 | Base | FACET-Terminal | 绝对提升 |
|:--|--:|--:|--:|--:|
| Qwen3.5-4B | 4B | 17.60 | **24.72** | **+7.12** |
| Qwen3.5-9B | 9B | 27.34 | **35.58** | **+8.24** |
| Qwen3.5-27B | 27B | 40.82 | **47.57** | **+6.75** |

仅使用 1.2K 条成功轨迹，三个模型规模均获得稳定提升。其中 9B 模型的绝对增益最大；4B 模型的相对提升为 **40.5%**。FACET-Terminal-Qwen3.5-27B 达到 **47.57**，与相同设置下 Qwen3.5-397B 的 **49.06** 相差 1.49 分，而参数规模约小 15 倍。

> 以上为论文预发布结果。公开排行榜中的模型可能采用不同 Agent、推理预算或评测设置，因此不应与本表直接横向比较。

## 与现有终端数据集对比

所有轨迹采集与任务评测均使用 `Terminus-2`。`Tests` 表示每个任务平均包含的可执行检查点数量，P@k 表示 pass@k（%）。

| 数据集 | 轨迹数 | 平均轮数 | 任务数 | Tests | P@1 | P@3 |
|:--|--:|--:|--:|--:|--:|--:|
| Nemotron-Terminal | 5K | 6.12 | 15K | 6.18 | 40.67 | 48.00 |
| Endless-Terminals | 200 | 4.53 | 2,492 | 5.51 | 83.00 | 87.00 |
| Terminal-Lego | 32K | 5.77 | 15K | 16.60 | 47.00 | 49.00 |
| TerminalWorld | 200 | **11.94** | 1,530 | 3.98 | 57.00 | 82.00 |
| Tmax | 500 | 11.14 | 15K | 3.29 | 80.00 | 86.00 |
| **FACET（Ours）** | **1.2K** | 11.86 | **6,078** | **22.77** | 27.00 | 35.00 |

FACET 的轨迹具有较长的交互跨度，并以平均 **22.77** 个可执行检查点提供更密集的验证。较低的任务级通过率反映了严格的合取式成功标准：Agent 必须同时满足主任务、次级产物、内容约束和跨产物一致性要求。

## 任务构造漏斗

| 阶段 | 数量 | 阶段保留率 |
|:--|--:|--:|
| 场景—技能种子 | 7,852 | — |
| 具有首次构建日志 | 7,841 | 99.86% |
| 初始环境构建成功 | 6,630 | 84.56% |
| 环境修复后成功 | 7,504 | 95.70% |
| 进入任务验证 | 7,446 | 99.23% |
| 首次验证通过 | 2,856 | 38.35% |
| 最终验证通过 | **6,078** | **81.63%** |

## 生成顺序消融

我们在相同的 100 条语义路径上比较三种任务组件生成顺序。初始有效率以实际进入验证的任务为分母，最终产出率以全部 100 条路径为分母。

| 策略 | 生成顺序 | 进入验证 | 初始有效 | 最终产出 |
|:--|:--|--:|--:|--:|
| **Forward（Ours）** | 指令 → 解法 → 验证器 | 99 | **46（46.5%）** | **83/100** |
| Reverse | 指令 → 验证器 → 解法 | 91 | 22（24.2%） | 63/100 |
| Joint | 同一次调用联合生成 | 96 | 36（37.5%） | 65/100 |

Forward 让验证器观察已生成的参考解法，从而更容易维持指令、执行行为与检查逻辑之间的契约一致性。需要注意，Forward 使用最多 5 轮修复，而 Reverse 和 Joint 使用最多 3 轮，因此最终产出率反映的是完整流水线配置，而非相同修复预算下的单独比较。

# 🔍 数据与任务分析

- **技能覆盖**：71,341 个来源技能覆盖 AI 与 Agent、软件与系统、数据分析、文档工作流以及多媒体创作五类能力。
- **长程交互**：成功训练轨迹平均包含 11.86 轮交互；95.6% 的轨迹以纯观察步骤开始。
- **严格验证**：教师 rollout 的单项检查通过率为 89.40%，但完整任务成功率仅为 20.94%，说明许多失败来自少量尚未满足的约束。
- **接近成功的失败**：在未成功的 rollout 中，54.00% 仅有 1–2 个验证检查失败，密集检查能够区分完全失败与接近完成的轨迹。

# 📦 安装

## 环境要求

- Python `3.11–3.13`
- [uv](https://docs.astral.sh/uv/)
- Docker（用于环境构造与执行验证）

```bash
git clone https://github.com/StoKou/FACET-Terminal.git
cd FACET-Terminal/facet
uv sync
```

# 🚀 快速开始

公开配置不会保存真实凭据。先设置模型密钥：

```bash
export FACET_API_KEY="your-api-key"
```

所有配置、脚本和 Python 代码都位于 `facet/`。进入该目录后，在 `configs/FORWARD.yaml` 中填写私有的 `api_base`、`model_name` 和输入 JSONL 路径：

```bash
uv run python facet_terminal/pipeline.py \
  --config configs/FORWARD.yaml \
  --strategy FORWARD
```

只运行一个阶段：

```bash
uv run python facet_terminal/pipeline.py \
  --config configs/FORWARD.yaml \
  --strategy FORWARD \
  --stage planning
```

实验策略：

```bash
uv run python facet_terminal/pipeline.py --config configs/REVERSE.yaml --strategy REVERSE
uv run python facet_terminal/pipeline.py --config configs/JOINT.yaml --strategy JOINT
```

# 📄 输入格式

默认输入是一行一个技能对的 JSONL：

```json
{
  "pair_id": "pair_demo",
  "skill_ids": ["skill_a", "skill_b"],
  "skill_summaries": ["summary a", "summary b"],
  "scenario_texts": ["initial context", "desired outcome"],
  "quality": {"overall_status": "ACCEPTED"}
}
```

代码还提供 `skill_objects_jsonl` 和可通过字段映射适配任意嵌套结构的 `mapped_jsonl`。

# 🗂️ 仓库结构

```text
FACET-Terminal/
├── README.md               # 默认中文项目说明
├── README_EN.md            # 英文项目说明
├── docs/                   # GitHub Pages 静态主页与论文图片
└── facet/                  # 全部开源代码、配置与脚本
    ├── common/             # 配置、IO、哈希、模型客户端与运行上下文
    ├── configs/            # 已脱敏的三种生成策略配置
    ├── facet_terminal/
    │   ├── stages/         # 场景、环境、生成、验证与修复阶段
    │   ├── harbor-template/ # Harbor 任务模板
    │   ├── pipeline.py     # 命令行入口与阶段路由
    │   └── prompts*.py     # 默认与实验策略提示词
    ├── scripts/            # 辅助脚本说明与扩展入口
    ├── tests/              # 单元测试
    ├── .env.example        # 环境变量示例
    ├── pyproject.toml      # Python 项目与依赖配置
    └── uv.lock             # 可复现依赖锁文件
```

# 🔒 开源与安全说明

- 本仓库不包含源数据、生成任务、轨迹、模型权重或运行产物。
- API 密钥通过 `FACET_API_KEY` 环境变量读取；`facet/.env*`、`facet/configs/local/` 和 `facet/` 下的运行目录均被忽略。
- 流水线会构建并执行生成的 Docker 任务。请在隔离的开发机或沙箱中运行，不要在包含敏感数据的生产主机上执行不可信任务。

# 🧪 测试

```bash
cd facet
uv run pytest
```

# ✉️ 联系方式

如有问题，欢迎联系：

📧 **Kou Shi** — [stokou@mail.ustc.edu.cn](mailto:stokou@mail.ustc.edu.cn)

# 📚 引用

如果 FACET 对你的研究有所帮助，请引用：

```bibtex
@misc{shi2026facet,
  title   = {{FACET}: Preserving Source Intent and Executable State in Terminal Task Synthesis},
  author  = {Kou Shi and Zun Wang and Qisheng Su and Shiting Huang and Ziao Zhang and Zhen Fang and Qingnan Ren and Jin Liu and Yu Zeng and Yiming Zhao and Lin Chen and Zehui Chen and Feng Zhao},
  year    = {2026},
  note    = {Preprint},
  url     = {https://github.com/StoKou/FACET-Terminal}
}
```
