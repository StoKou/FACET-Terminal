<div align="center">

[简体中文](README.md) | [English](README_EN.md)

<img src="asset/facet-banner.png" alt="FACET: Preserving Source Intent and Executable State in Terminal Task Synthesis" width="100%">

<p>
  <img src="https://img.shields.io/badge/Task-Terminal_Task_Synthesis-2D8BC3" alt="Task">
  <img src="https://img.shields.io/badge/Framework-FACET-5AAFE0" alt="Framework">
  <a href="https://arxiv.org/abs/2608.18580"><img src="https://img.shields.io/badge/arXiv-2608.18580-B31B1B" alt="arXiv"></a>
  <img src="https://img.shields.io/badge/Python-3.11--3.13-3776AB" alt="Python">
  <img src="https://img.shields.io/badge/License-Apache--2.0-7AAED1" alt="License">
</p>

[[🌐 项目主页](https://stokou.github.io/FACET-Terminal/)]
[[📖 论文](https://arxiv.org/abs/2608.18580)]
[[🤗 数据](https://huggingface.co/datasets/FACET-Terminal/FACET-Terminal-Tasks-6k)]
[[🤗 模型](https://huggingface.co/FACET-Terminal)]

</div>

---

# 🔥 动态

- **`2026-08-20`**：发布包含 **6,020** 个任务的 FACET-Terminal-Tasks-6k 数据集及 4B、9B、27B 模型。
- **`2026-08-20`**：FACET 论文已发布于 [arXiv](https://arxiv.org/abs/2608.18580)。
- **`2026-08-19`**：发布 FACET-Terminal 任务合成代码预览版与项目主页。

# 🤗 公开资源

| 类型 | 资源 |
| --- | --- |
| 数据集 | [FACET-Terminal-Tasks-6k](https://huggingface.co/datasets/FACET-Terminal/FACET-Terminal-Tasks-6k)（6,020 个公开任务） |
| 4B 模型 | [FACET-Terminal-Qwen3.5-4B](https://huggingface.co/FACET-Terminal/FACET-Terminal-Qwen3.5-4B) |
| 9B 模型 | [FACET-Terminal-Qwen3.5-9B](https://huggingface.co/FACET-Terminal/FACET-Terminal-Qwen3.5-9B) |
| 27B 模型 | [FACET-Terminal-Qwen3.5-27B](https://huggingface.co/FACET-Terminal/FACET-Terminal-Qwen3.5-27B) |

# 💡 FACET

**FACET**（Fine-grained Agentic Construction of Executable Tasks）从相关 Agent Skills 出发，合成复杂、连贯且可执行验证的终端任务。

它围绕两个核心原则设计：

- **保留源意图**：在多阶段生成中持续保留能力、依赖、输入输出约束和过程知识。
- **共享可执行状态**：先构造并修复环境，再让指令、解法和验证器基于同一容器状态完成生成。

![FACET Pipeline](asset/facet-pipeline.png)

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

<div align="center">
  <img src="asset/facet-main-results.png" alt="FACET 在 Terminal-Bench 2.1 上的主实验结果" width="100%">
</div>

仅使用 1.2K 条成功轨迹，三个模型规模均获得稳定提升。其中 9B 模型的绝对增益最大；4B 模型的相对提升为 **40.5%**。FACET-Terminal-Qwen3.5-27B 达到 **47.57**，与相同设置下 Qwen3.5-397B 的 **49.06** 相差 1.49 分，而参数规模约小 15 倍。

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
├── asset/                  # README 专用图片
├── docs/                   # GitHub Pages 静态主页及其资源
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
  eprint  = {2608.18580},
  archivePrefix = {arXiv},
  primaryClass  = {cs.AI},
  url     = {https://arxiv.org/abs/2608.18580}
}
```
