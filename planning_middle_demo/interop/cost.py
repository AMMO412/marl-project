# -*- coding: utf-8 -*-
"""三目标代价模型（吸收自 M2）：时效 / 风险 / 能耗。

代价只用于候选评分，不替代硬约束（能力、时间窗、禁航区、续航）。
三类系数是演示值，真实数据到位只改这张表；报告中必须保留“演示值”
标签，不能当成装备实测。
"""

import math
from typing import Any, Dict, Optional, Sequence, Tuple

from .geometry import point_in_polygon

Point = Tuple[float, float]

OBJECTIVES = ("timeliness", "energy", "risk", "balanced")
DEFAULT_WEIGHTS = {
    "timeliness": (1.0, 0.0, 0.0),
    "energy": (0.0, 0.0, 1.0),
    "risk": (0.0, 1.0, 0.0),
    "balanced": (0.5, 0.3, 0.2),
}
OBJECTIVE_LABELS = {
    "timeliness": "时效（完工时间）",
    "energy": "能耗",
    "risk": "风险（威胁暴露）",
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
RISK_SAMPLE_M = 5.0


def _polygon(constraint: Dict[str, Any]):
    area = constraint.get("area")
    polygon = area.get("polygon") if isinstance(area, dict) else area
    if not polygon or len(polygon) < 3:
        return None
    return [(float(p[0]), float(p[1])) for p in polygon]


class CostModel(object):
    def __init__(self, scenario, objective: str = "timeliness",
                 weights: Optional[Sequence[float]] = None):
        if objective not in OBJECTIVES:
            raise ValueError("objective 必须是 %s 之一" % "/".join(OBJECTIVES))
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
            if air and applies != "all":
                continue
            intensity = float(item.get("intensity", 1.0))
            polygon = [(x * self.scale, y * self.scale)
                       for x, y in _polygon(item)]
            for i in range(len(path) - 1):
                x0, y0 = path[i]
                x1, y1 = path[i + 1]
                length = math.hypot(x1 - x0, y1 - y0)
                steps = max(1, int(math.ceil(length / RISK_SAMPLE_M)))
                for k in range(steps):
                    t = (k + 0.5) / steps
                    x = x0 + (x1 - x0) * t
                    y = y0 + (y1 - y0) * t
                    if point_in_polygon((x, y), polygon):
                        risk += intensity * (length / steps) / speed * factor
            if point_in_polygon(target_point_m, polygon):
                risk += intensity * max(0.0, duration_s) * factor
        return risk

    def candidate_cost(self, end_s: float, risk: float, energy: float) -> float:
        w_t, w_r, w_e = self.weights
        time_norm = float(end_s) / self.time_ref
        risk_norm = float(risk) / RISK_REF
        energy_norm = float(energy) / ENERGY_REF
        # 极小项只做同分裁决，避免 risk 目标在无威胁时所有候选都为 0。
        return (w_t * time_norm + w_r * risk_norm + w_e * energy_norm
                + 1e-3 * time_norm + 1e-9 * energy_norm)

    def metrics(self, assignments) -> Dict[str, Any]:
        makespan = max([a.end_s for a in assignments] or [0.0])
        total_energy = sum(a.energy for a in assignments)
        total_risk = sum(a.risk for a in assignments)
        return {
            "objective": self.objective,
            "weights": {
                "time": round(self.weights[0], 4),
                "risk": round(self.weights[1], 4),
                "energy": round(self.weights[2], 4),
            },
            "makespan_s": round(makespan, 3),
            "total_energy": round(total_energy, 3),
            "total_risk": round(total_risk, 3),
        }
