# 配置文件

- `FORWARD.yaml`：FACET 默认流程，按 instruction → solution → verifier 的顺序构造任务。
- `REVERSE.yaml`：实验流程，按 instruction → verifier → solution 的顺序构造任务。
- `JOINT.yaml`：实验流程，在一次调用中联合生成三个任务组件。

公开配置仅包含安全占位符。模型密钥默认从 `FACET_API_KEY` 环境变量读取；本地私有配置请放入 `configs/local/`，该目录不会被 Git 跟踪。
