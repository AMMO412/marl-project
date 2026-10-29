# -*- coding: utf-8 -*-
"""
metrics.py —— 冲突口径与消解率统计

为什么要单独一个文件：
「20 回合内时序冲突消解率 ≥95%」这句话里，**每一个词都没有定义**。
不把口径定死就算出百分比，那个数字是假的。

本文件给出一套我方暂定的口径，见 ConflictTracker 的注释。
"""

from typing import Dict, List, Optional


class ConflictTracker:
    """时序冲突的口径化统计。

    三条口径（我方暂定，依据 SPEC.md）：

    1. **冲突实例的身份 = (作业号, 冲突类型)**。
       去重是必须的：同一个问题（比如某作业排不进时间窗）在每次滚动重规划
       时都会被重新发现一次。不去重，分母被灌水，消解率会虚高到没有意义。

    2. **消解 = 该冲突不再出现，或本轮被显式消除**。
       - `shift`（后移错开）本轮即消解
       - `defer`（本轮放弃）不算本轮消解；下一轮若排上了，记为跨轮消解
       - 结束时仍未消解的，单列出来，不许静默消失

    3. **"20 回合内" = 从首次发现到消解，间隔不超过 20 步**。
       这是我方对「20 回合」的暂定解释。**与"一次输出 20 步"是否为同一件事，
       尚未经甲方确认**（见方案第七节第 1 问）。
    """

    def __init__(self, window: int = 20):
        self.window = window
        self.first_seen: Dict[tuple, int] = {}
        self.resolved_at: Dict[tuple, int] = {}
        self.resolved_by: Dict[tuple, str] = {}

    def observe(self, events: List[Dict], step: int) -> None:
        """喂入本轮规划产生的 events。"""
        seen_now = set()
        for e in events:
            kind = e.get("kind")
            if kind == "conflict":
                key = (e.get("tid"), e.get("type"))
                seen_now.add(key)
                if key not in self.first_seen:
                    self.first_seen[key] = step
            elif kind == "resolved":
                key = (e.get("tid"), e.get("type"))
                if key in self.first_seen and key not in self.resolved_at:
                    # defer 是"本轮放弃"，不算本轮消解，留给下一轮
                    if e.get("by") != "defer":
                        self.resolved_at[key] = step
                        self.resolved_by[key] = e.get("by", "?")

        # 本轮不再出现的未决冲突 → 视为跨轮消解
        for key in self.first_seen:
            if key in self.resolved_at:
                continue
            if key not in seen_now:
                self.resolved_at[key] = step
                self.resolved_by[key] = "disappeared"

    def report(self) -> Dict:
        total = len(self.first_seen)
        if total == 0:
            return dict(window=self.window, total=0, resolved=0, rate=None,
                        within_window=0, within_rate=None, unresolved=[],
                        by_type={}, how={})
        resolved = len(self.resolved_at)
        within = sum(1 for k, at in self.resolved_at.items()
                     if at - self.first_seen[k] <= self.window)
        unresolved = [
            dict(tid=k[0], type=k[1], since=v, waited=None)
            for k, v in self.first_seen.items() if k not in self.resolved_at
        ]
        by_type: Dict[str, Dict[str, int]] = {}
        for k in self.first_seen:
            t = k[1] or "?"
            d = by_type.setdefault(t, dict(found=0, resolved=0))
            d["found"] += 1
            if k in self.resolved_at:
                d["resolved"] += 1
        how: Dict[str, int] = {}
        for k, by in self.resolved_by.items():
            how[by] = how.get(by, 0) + 1
        return dict(
            window=self.window,
            total=total,
            resolved=resolved,
            rate=resolved / total,
            within_window=within,
            within_rate=within / total,
            unresolved=unresolved,
            by_type=by_type,
            how=how,
        )


def format_report(rep: Dict, raw_conflicts: int = 0) -> str:
    """把口径报告排版成可读文本。"""
    lines = []
    lines.append("冲突口径（我方暂定，去重后）")
    lines.append("  冲突实例总数：%d" % rep["total"])
    if raw_conflicts:
        lines.append("  原始事件计数：%d  ← 未去重，同一件事被重复计了 %.1f 倍"
                     % (raw_conflicts,
                        raw_conflicts / rep["total"] if rep["total"] else 0))
    if rep["total"] == 0:
        lines.append("  本次运行没有检测到冲突，消解率无定义（分母为零）")
        return "\n".join(lines)
    lines.append("  已消解：%d（%.1f%%）" % (rep["resolved"], 100 * rep["rate"]))
    lines.append("  其中在 %d 步窗口内消解：%d（%.1f%%）  ← 这是对应 2.2（3）的那个数"
                 % (rep["window"], rep["within_window"], 100 * rep["within_rate"]))
    if rep["by_type"]:
        lines.append("  按类型：" + "、".join(
            "%s %d/%d" % (t, d["resolved"], d["found"])
            for t, d in rep["by_type"].items()))
    if rep["how"]:
        lines.append("  消解方式：" + "、".join(
            "%s×%d" % (k, v) for k, v in rep["how"].items()))
    if rep["unresolved"]:
        lines.append("  未消解（不能静默省略）：%s"
                     % [(u["tid"], u["type"]) for u in rep["unresolved"]])
    return "\n".join(lines)
