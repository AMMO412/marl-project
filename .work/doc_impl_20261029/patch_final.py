from pathlib import Path

p = Path(r"D:\Desktop\MARL项目\.work\doc_impl_20261029\build_report.py")
t = p.read_text(encoding="utf-8")

# 表 2 表头与列宽
t = t.replace(
    '["类别", "号段", "底盘 / 机体（m）", "整机包络（m）", "包络半径（m）", "初始高度（m）"]',
    '["类别", "号段", "底盘/机体", "整机包络", "包络半径", "初始高度"]')
t = t.replace("widths=[2.8, 1.8, 4.0, 4.0, 2.2, 2.0],", "widths=[2.6, 2.2, 3.8, 3.8, 2.2, 2.2],")
t = t.replace(
    'r.note("注：轮式与履带平台在 SDF 中共用同一代理碰撞盒，因此包络尺寸相同；"',
    'r.note("注：表中长度单位为米（m）。轮式与履带平台在 SDF 中共用同一代理碰撞盒，因此包络尺寸相同；"')

# 表 18 表头与列宽
t = t.replace(
    '["类别", "速度（单位/步）", "作业效率", "续航", "载荷", "传感器", "弹药"]',
    '["类别", "速度", "作业效率", "续航", "载荷", "传感器", "弹药"]')
t = t.replace("widths=[3.2, 3.2, 2.4, 2.0, 2.0, 2.0, 2.0],", "widths=[2.8, 2.2, 2.4, 2.0, 2.0, 2.4, 2.0],")
t = t.replace(
    'r.note("注：以上为演示暂定值，不是厂商实测性能；真实数据到位后只改参数表，不改规划与判定逻辑。")',
    'r.note("注：速度单位为场景单位/步；以上为演示暂定值，不是厂商实测性能；真实数据到位后只改参数表，不改规划与判定逻辑。")')

# 表 19 路径改为相对路径
t = t.replace('["场景初始状态", "planning_middle_demo/scenarios/sdf_initial_state.json", "平台位姿、尺寸、障碍、道路"],',
              '["场景初始状态", "scenarios/sdf_initial_state.json", "平台位姿、尺寸、障碍、道路"],')
t = t.replace('["任务场景", "planning_middle_demo/scenarios/asl_city.json", "指令参数与编成"],',
              '["任务场景", "scenarios/asl_city.json", "指令参数与编成"],')
t = t.replace('["毁伤运行", "…/outputs/workbench_20261029_181813_611337/", "报告、轨迹与回放"],',
              '["毁伤运行", "outputs/workbench_20261029_181813_611337/", "报告、轨迹与回放"],')
t = t.replace('["压制运行", "…/outputs/asl_city_suppress/", "同上"],',
              '["压制运行", "outputs/asl_city_suppress/", "同上"],')
t = t.replace('["夺占运行", "…/outputs/asl_city_seize/", "同上"],',
              '["夺占运行", "outputs/asl_city_seize/", "同上"],')
t = t.replace("widths=[3.4, 8.4, 5.0], align=[\"center\", \"left\", \"left\"])",
              "widths=[3.0, 8.6, 5.2], align=[\"center\", \"left\", \"left\"])\n    r.note(\"注：除实现说明外，表中路径均相对 planning_middle_demo/。\")")

# 参考资料后补一句收尾
t = t.replace('        run = p.add_run(item)\n        set_run_font(run, SONG, 10.5)',
              '        run = p.add_run(item)\n        set_run_font(run, SONG, 10.5)\n'
              '    r.para("以上资料与运行记录随项目一并保存；复现时请使用独立输出目录，不要覆盖已有记录。")')

# TOC 页码（依据 draft6 的分页）
toc = {
    "1 概述": 3, "1.1 编写目的与范围": 3, "1.2 任务与对象": 3, "1.3 总体组成": 3, "1.4 术语与口径": 4,
    "2 输入与初始状态": 5, "2.1 场景与平台初始状态": 5, "2.2 任务指令": 6, "2.3 兵力编成": 7, "2.4 场景几何与障碍": 7,
    "3 关键实现": 9, "3.1 任务规划与分配": 9, "3.2 指令、反馈与重规划": 9, "3.3 运动与避障": 10,
    "3.4 到位行为状态机": 11, "3.5 效果判定与逐项结算": 12, "3.6 工作台与回放": 13,
    "4 验证结果": 14, "4.1 运行配置": 14, "4.2 毁伤任务结果": 14, "4.3 压制与夺占结果": 16,
    "4.4 测试与可复现性": 16, "4.5 结果解读": 17,
    "5 达成情况与差距": 17, "5.1 需求对照": 17, "5.2 已达成": 18, "5.3 部分达成": 19,
    "5.4 未实现": 19, "5.5 风险与建议": 19,
    "6 附录": 20, "6.1 关键参数汇总": 20, "6.2 产物与文件": 20, "6.3 参考资料": 21,
}
old = "TOC_PAGES = {}"
new = "TOC_PAGES = {\n" + "".join('    "%s": %d,\n' % (k, v) for k, v in toc.items()) + "}"
t = t.replace(old, new)

p.write_text(t, encoding="utf-8")
print("patched", len(toc), "toc entries")
