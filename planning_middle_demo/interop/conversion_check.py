"""Describe representational gaps before writing a legacy scene.

No task, resource limit, or runtime schema is changed to make conversion pass.
"""


def v2_conversion_gaps(scenario):
    import fleet

    gaps = []

    def add(code, path, detail):
        gaps.append(dict(code=code, path=path, detail=detail))

    for task in scenario.tasks:
        path = "tasks." + task.task_id
        add("TASK_BEHAVIOR", path + ".task_type",
            "%s尚无无损的旧行为绑定；仅存_task_type会被读取为custom" % task.task_type)
        kinds = set(task.target)
        if not kinds <= {"point", "key_point"}:
            add("TASK_GEOMETRY", path + ".target",
                "旧作业pos不能表达完整%s；不能取首点或中心点代替" % "/".join(sorted(kinds)))
        if task.depends_on:
            add("TASK_DEPENDENCIES", path + ".depends_on", "旧作业入口没有等价的前置任务契约")
        if task.required_capabilities:
            add("TASK_CAPABILITIES", path + ".required_capabilities",
                "旧作业不消费能力编码，不能用payload/sensor推测换算")
        if task.max_units is not None and task.max_units != task.min_units:
            add("TASK_UNIT_RANGE", path + ".max_units", "固定crew不能保留最少/最多数量区间")
        if any(t != int(t) for t in (task.window_start_s, task.window_end_s)):
            add("TIME_PRECISION", path + ".window", "旧入口要求整数步；不能静默四舍五入秒数")
        if task.params:
            add("TASK_PARAMETERS", path + ".params",
                "尚无完整参数映射；duration_s不等于旧作业work，不能直接赋值")

    for platform in scenario.platforms:
        path = "formation.units." + platform.unit_id
        profile = fleet.PLANNING_PARAMS[platform.platform_class]
        pairs = (("speed_mps", platform.speed_mps, "speed"),
                 ("work_rate", platform.work_rate, "work_rate"),
                 ("battery", platform.battery, "battery"),
                 ("payload", platform.payload, "payload"),
                 ("sensor", platform.sensor, "sensor"),
                 ("move_cost", platform.move_cost, "move_cost"),
                 ("work_cost", platform.work_cost, "work_cost"))
        for name, value, legacy_key in pairs:
            if value != profile[legacy_key]:
                add("PLATFORM_PROFILE", path + "." + name,
                    "输入%r，旧入口会取默认%r；旧契约禁止通过场景覆盖画像"
                    % (value, profile[legacy_key]))
        if platform.status != "READY":
            add("PLATFORM_STATUS", path + ".status", "旧入口会重新构造可用平台，不能丢弃%s状态" % platform.status)
        if platform.heading_rad != 0 or platform.altitude_m != 0:
            add("INITIAL_POSE", path, "旧场景只传二维pos，初始航向或高度无法完整保留")
        add("PLATFORM_ENDURANCE", path + ".endurance_s",
            "旧入口没有累计续航秒数契约；不能转换成模型battery")

    if scenario.constraints:
        add("WORLD_CONSTRAINTS", "constraints",
            "%d项场景约束没有等价运行接口，不能丢弃后生成场景" % len(scenario.constraints))
    add("TIME_BASIS", "meta", "外部时间为秒，旧协议为demo_sim_steps；尚无已验证的时钟映射")
    if scenario.cell_size_m != 1:
        add("COORDINATE_SCALE", "meta.cell_size_m", "旧入口不按cell_size_m转换运动单位")
    return gaps
