# 融合版主程序

默认入口为 [interop](interop/README.md)，复用本目录的执行基座与工作台。

- 唯一推荐入口：根目录 `启动工作台.cmd`；程序内同名脚本为其调用实现。
- `interop/`：统一接口、规划与运行适配。
- `tests/`：基座及 `test_interop*.py` 融合对接测试。
- `config/`、`scenarios/`：基座配置和场景。
- `interop/scenarios/`：融合输入消息与编成表。
- `docs/`：现有设计及接口文档。
- `outputs/`：已有运行报告及回放，保留路径。

[基座详细说明](README_v2.md) 用于查阅兼容能力，不能将其中所有能力视为融合层支持范围。
