# -*- coding: utf-8 -*-
"""三目标代价模型（吸收自 M2）：时效 / 暴露 / 能耗。

代价只用于候选评分，不替代硬约束（能力、时间窗、禁航区、续航）。
三类系数是演示值，真实数据到位只改这张表；报告中必须保留“演示值”
标签，不能当成装备实测。

暴露度（exposure，2026-11 起取代旧的“空间分散度”）：
    暴露量 = Σ_威胁区 强度 × 区内停留秒数 × 平台信号特征 × (1 − 防护)
    被侦测概率 P = 1 − exp(−λ × 暴露量)，λ 为演示探测率。
    规划代价用暴露量（线性），因为 P 是暴露量的单调函数，最小化 P 等价于
    最小化总暴露量；线性项还能避免“概率已接近 1 的平台再多暴露也不吃亏”
    这类饱和假象。威胁区内的在途与作业停留都计入（见 path_risk）。

注意：空间分散本身不是优化目标。现有场景数据只有威胁区多边形和强度，
没有传感器作用距离/探测概率场，扎堆不会直接提高被侦测概率；分散只在
“少派平台进威胁区、缩短区内停留”时间接降低暴露。
"""

import math
from typing import Any, Dict, Optional, Sequence, Tuple

from .geometry import point_in_polygon, segment_polygon_overlap_length

Point = Tuple[float, float]

OBJECTIVES = ("timeliness", "exposure", "energy", "risk", "balanced")
# 2026-11：工作台第三项从“空间分散度”改为“暴露度（被侦测概率）”。
# dispersion 只作为旧运行/旧脚本的别名保留，不再代表空间摊开。
LEGACY_OBJECTIVES = {"dispersion": "exposure"}
DEFAULT_WEIGHTS = {
    "timeliness": (1.0, 0.0, 0.0),
    "exposure": (0.0, 1.0, 0.0),
    "energy": (0.0, 0.0, 1.0),
    "risk": (0.0, 1.0, 0.0),
    "balanced": (0.5, 0.3, 0.2),
}
OBJECTIVE_LABELS = {
    "timeliness": "时效（完工时间）",
    "exposure": "暴露度（被侦察到的概率）",
    "energy": "能耗",
    "risk": "风险（威胁暴露，旧名）",
    "balanced": "均衡（0.5/0.3/0.2）",
}

# 演示系数：每米能耗、每秒能耗
CLASS_ENERGY = {
    "UGV": (0.05, 0.20),
    "TANK": (0.08, 0.30),
    "PLANE": (0.12, 0.40),
    "WING": (0.09, 0.25),
}
CLASS_SIGNATURE = {"UGV": 0.8, "TANK": 1.0, "PLANE": 0.6, "WING": 0.5}
CLASS_PROTECTION = {"UGV": 0.2, "TANK": 0.5, "PLANE": 0.0, "WING": 0.0}

RISK_REF = 10.0
ENERGY_REF = 1000.0
# 探测率 λ（1/暴露当量）：1 当量约 9.5%，10 当量约 63% 被侦测。
# 演示值；真实传感器/探测数据到位后只改这里，报告仍需标注“演示值”。
EXPOSURE_RATE = 0.1


def _polygon(constraint: Dict[str, Any]):
    area = constraint.get("area")
    polygon = area.get("polygon") if isinstance(area, dict) else area
    if not polygon or len(polygon) < 3:
        return None
    return [(float(p[0]), float(p[1])) for p in polygon]


class CostModel(object):
    def __init__(self, scenario, objective: str = "timeliness",
                 weights: Optional[Sequence[float]] = None):
        objective = LEGACY_OBJECTIVES.get(objective, objective)
        if objective not in OBJECTIVES:
            raise ValueError("objective 必须是 %s 之一"
                             % "/".join(OBJECTIVES + tuple(LEGACY_OBJECTIVES)))
        self.scenario = scenario
        self.scale = float(scenario.cell_size_m)
        self.objective = objective
        raw = tuple(float(w) for w in (weights or DEFAULT_WEIGHTS[objective]))
        if len(raw) != 3 or min(raw) < 0:
            raise ValueError("weights 必须是三个非负数 (time, risk, energy)")
        total = sum(raw)
        self.weights = raw if total <= 1e-12 else tuple(w / total for w in raw)
        self.threats = [item for item in scenario.constraints
                        if item.get("type") == "threat" and _polygon(item)]
        self.time_ref = max([float(task.window_end_s)
                             for task in scenario.tasks] + [1.0])

    def energy(self, platform, path_length_m: float, duration_s: float) -> float:
        e_m, e_s = CLASS_ENERGY.get(platform.platform_class, (0.1, 0.3))
        return max(0.0, path_length_m) * e_m + max(0.0, duration_s) * e_s

    def path_risk(self, platform, path: Sequence[Point], speed_mps: float,
                  duration_s: float, target_point_m: Point) -> float:
        if not self.threats:
            return 0.0
        air = platform.is_air
        signature = CLASS_SIGNATURE.get(platform.platform_class, 1.0)
        protection = CLASS_PROTECTION.get(platform.platform_class, 0.0)
        factor = signature * max(0.0, 1.0 - protection)
        speed = max(float(speed_mps), 1e-6)
        risk = 0.0
        for item in self.threats:
            applies = item.get("applies_to", "ground")
            if air and applies not in ("air", "all"):
                continue
            if not air and applies not in ("ground", "all"):
                continue
            intensity = float(item.get("intensity", 1.0))
            polygon = [(x * self.scale, y * self.scale)
                       for x, y in _polygon(item)]
            for i in range(len(path) - 1):
                x0, y0 = path[i]
                x1, y1 = path[i + 1]
                overlap = segment_polygon_overlap_length(
                    (x0, y0), (x1, y1), polygon)
                risk += intensity * overlap / speed * factor
            if point_in_polygon(target_point_m, polygon):
                risk += intensity * max(0.0, duration_s) * factor
        return risk

    def detection_probability(self, exposure: float) -> float:
        """暴露量 → 至少被侦测一次的概率（独立探测、泊松近似）。

        只用于报告与阈值判断，不参与候选排序：P 是暴露量的单调函数，
        排序用线性暴露量即可，且不会因 P 饱和而放过“再多暴露一点”的候选。
        """
        return 1.0 - math.exp(-EXPOSURE_RATE * max(0.0, float(exposure)))

    def candidate_cost(self, end_s: float, risk: float, energy: float) -> float:
        w_t, w_r, w_e = self.weights
        time_norm = float(end_s) / self.time_ref
        risk_norm = float(risk) / RISK_REF
        energy_norm = float(energy) / ENERGY_REF
        # exposure 目标：w=(0,1,0)，按暴露量线性排序。
        # 极小项只做同分裁决，避免无威胁时所有候选都为 0。
        return (w_t * time_norm + w_r * risk_norm + w_e * energy_norm
                + 1e-3 * time_norm + 1e-9 * energy_norm)

    def metrics(self, assignments) -> Dict[str, Any]:
        makespan = max([a.end_s for a in assignments] or [0.0])
        total_energy = sum(a.energy for a in assignments)
        total_exposure = sum(a.risk for a in assignments)
        per_platform = [self.detection_probability(a.risk)
                        for a in assignments]
        return {
            "objective": self.objective,
            "objective_label": OBJECTIVE_LABELS.get(self.objective,
                                                    self.objective),
            "weights": {
                "time": round(self.weights[0], 4),
                "risk": round(self.weights[1], 4),
                "exposure": round(self.weights[1], 4),
                "energy": round(self.weights[2], 4),
            },
            "makespan_s": round(makespan, 3),
            "total_energy": round(total_energy, 3),
            # 暴露量沿用历史的 total_risk 字段名，避免旧报表读取方断链。
            "total_exposure": round(total_exposure, 3),
            "total_risk": round(total_exposure, 3),
            "detection_probability": round(
                self.detection_probability(total_exposure), 4),
            "max_platform_detection_probability": round(
                max(per_platform) if per_platform else 0.0, 4),
            "expected_detections": round(sum(per_platform), 4),
        }
