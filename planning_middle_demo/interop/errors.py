# -*- coding: utf-8 -*-
"""统一的错误类型：输入契约错误与规划错误分开。"""


class WireError(ValueError):
    """输入消息 / 编成表不符合 4.1/4.2 契约时抛出。"""


class PlanningError(ValueError):
    """规划过程中无法继续（分解失败、依赖成环等）时抛出。"""


class UnsupportedFeature(WireError):
    """输入合法但超出本层融合范围（如 T-ASL）时抛出。"""
