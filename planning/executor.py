# -*- coding: utf-8 -*-
"""
executor.py —— 下层替身执行器

真实下层还没好，用这个类按计划"假装执行"，并回传反馈。
按会议一·31 的建议支持注入噪声（延迟、失败），用来观察偏差判定的行为。

真实下层到位后，只要换掉这个类（保持 step() 的返回结构），
planner.py 和 run_flow.py 都不用动。
"""

import math
import random
from typing import Dict, List, Tuple

from contract import Feedback, GroupSnapshot, Plan, dist


class StubExecutor:
    """按计划推进进度的替身执行器。"""

    def __init__(self, seed: int = 0, delay_prob: float = 0.0, fail_prob: float = 0.0):
        self.rng = random.Random(seed)
        self.delay_prob = delay_prob      # 每台每步"磨洋工"的概率
        self.fail_prob = fail_prob        # 每个作业每步失败的概率
        # 移动能耗只在这条指派开工时记一次。同一个 (作业,平台,开工步) 记过就不再记，
        # 否则每次重规划都会把同一段路重复扣一遍电。
        self._charged_move: set = set()

    def step(self, plan: Plan, snapshot: GroupSnapshot, now: int):
        """推进一步。返回 (反馈列表, 事件列表)。"""
        pmap = {p.pid: p for p in snapshot.platforms}
        tmap = {t.tid: t for t in snapshot.tasks}
        events: List[Dict] = []
        feedbacks: List[Feedback] = []

        # 本步应该开工的作业
        active = {}
        for a in plan.assignments:
            if a.start <= now < a.end:
                active[a.tid] = a

        busy = set()
        for a in active.values():
            busy.update(a.pids)

        for tid, a in active.items():
            t = tmap[tid]
            if t.status in ("done", "failed"):
                continue
            # 噪声：执行失败
            if self.fail_prob and self.rng.random() < self.fail_prob:
                t.status = "failed"
                events.append(dict(kind="fail", tid=tid, at=now,
                                   note="替身注入的执行失败"))
                continue
            gained = 0.0
            for pid in a.pids:
                p = pmap.get(pid)
                if p is None or not p.alive:
                    continue
                # 能耗模型（我方暂定，与 contract.PLATFORM_SPECS 同源）：
                #   移动耗电 = 移动步数 × move_cost，开工时一次记清
                #   作业耗电 = 作业步数 × work_cost，每步记
                # 必须分两项：否则"跑得快"和"干得快"混成一个数，
                # 规划器的 energy 目标就学不出、也验不出差别。
                key = (tid, pid, a.start)
                if key not in self._charged_move:
                    self._charged_move.add(key)
                    steps = int(math.ceil(dist(p.pos, t.pos)
                                          / max(p.speed, 1e-6)))
                    p.battery = max(0.0, p.battery - steps * p.move_cost)
                p.pos = t.pos          # 原型简化：开工即视为已到达作业点
                # 位置必须更新。否则下次重规划时"到达时间"还是原值，
                # 而 now 已经在往前走，开工时间会被一遍遍往后推。
                # 噪声：延迟
                if self.delay_prob and self.rng.random() < self.delay_prob:
                    events.append(dict(kind="noise", type="delay",
                                       tid=tid, pid=pid, at=now))
                    continue
                gained += p.work_rate
                p.battery = max(0.0, p.battery - p.work_cost)
            t.progress += gained
            t.status = "running"
            if t.progress >= t.work:
                t.status = "done"
                events.append(dict(kind="task_done", tid=tid, at=now))
            for pid in a.pids:
                p = pmap.get(pid)
                if p is None:
                    continue
                feedbacks.append(Feedback(pid=pid, tid=tid, step=now,
                                          progress=round(t.progress, 2),
                                          status=t.status,
                                          battery=round(p.battery, 1), pos=p.pos))

        # 空闲平台也要有反馈：闭环里"没消息"和"在干活"是两回事
        for p in snapshot.platforms:
            if p.pid not in busy:
                feedbacks.append(Feedback(pid=p.pid, tid=None, step=now,
                                          progress=0.0, status="idle",
                                          battery=round(p.battery, 1), pos=p.pos))
        return feedbacks, events

    def kill(self, snapshot: GroupSnapshot, pid: str) -> bool:
        """模拟成员损失（上层编组通知失联）。返回是否真的杀掉了一台。"""
        for p in snapshot.platforms:
            if p.pid == pid and p.alive:
                p.alive = False
                return True
        return False
