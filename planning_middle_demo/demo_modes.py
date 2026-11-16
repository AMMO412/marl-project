"""Product-facing definitions of the five local fault-injection demos."""
MODES = {
    'normal': dict(label='正常执行', description='不额外注入故障，执行当前任务行为；任务本身仍可能失败。'),
    'failure': dict(label='失败重试', description='首任务首次下发后第 2 步注入任务级失败，释放成员后按重试上限重新分配。'),
    'timeout': dict(label='超时恢复', description='首任务首次尝试停滞 1000 步，超过预计结束时刻及宽限后取消，收到取消确认后重试。此模式使用作业进度模型，关闭到位行为。'),
    'kill': dict(label='成员失联', description='从第 8 步起，在首任务有已下发成员时仅注入一台失联，剔除该成员并触发重规划。'),
    'deviation': dict(label='进度偏差', description='首个协同作业的进度速率降为 70%，落后阈值后触发重规划。此模式使用作业进度模型，关闭到位行为；不保证自动修复或完成。'),
}
PROGRESS_MODES = ('timeout', 'deviation')


def mode_info(mode):
    return dict(mode=mode, uses_task_behavior=mode not in PROGRESS_MODES, **MODES[mode])
