# 2026-10-22 审查复现产物

完整对比与待修清单统一维护在 Obsidian：
`D:/obsidianNOTE/ammo/10_项目/MARL/审查_taskalloc与planning对比_2026-10-22.md`。

`reproduce_planning.py` 用标准库复现规划、时间窗和统计问题；
`reproduce_taskalloc.py` 使用现有 WSL 依赖检查真实环境和评估函数。
两个脚本不训练模型、不修改业务源码。输出记录在对应的 `*_probes.jsonl`。
运行前应核对 `source_hashes.json`；后续代码变化可能修复其中部分问题。

在项目根目录的 PowerShell 运行：

```powershell
py outputs/review_2026-10-22/reproduce_planning.py
wsl -d Ubuntu --exec env PYTHONPATH=/home/ammo/MARLlib /home/ammo/miniconda3/envs/marllib/bin/python /mnt/c/Users/ammo/Desktop/MARL项目/outputs/review_2026-10-22/reproduce_taskalloc.py
```

第一条检查规则规划及冲突统计，第二条检查旧环境、V2 和冻结评估的场景配对。
审查时 V2 导入、ID 映射和训练信息接口已被其他窗口修复；末次探针显示这些项通过。

原有 planning 统一回归在其目录内运行，16/16 通过；本次额外复现了原回归遗漏的边界。
旧环境默认自测输出误刷新了 `taskalloc/taskalloc_baseline/baseline.json`，详情见审查笔记；
模型、训练结果与已有冻结评估文件未被本次审查改动。

笔记修改前备份在 `obsidian_before_2026-10-22_212039/`，其 `manifest.json`
记录原路径与修改前/后的 SHA256。恢复时应先保留后续的新编辑，再只恢复所需笔记或片段；
不要重置整个笔记库。本次修改均未提交。
