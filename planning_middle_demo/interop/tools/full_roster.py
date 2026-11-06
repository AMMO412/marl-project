# -*- coding: utf-8 -*-
"""把 SDF 里解析出的全部平台并入编成表。

样例原本只保留参战的几台平台，地图文件（``container_00_combined_scene.sdf``）
解析出的其余平台在演示里看不到。本工具按 SDF 出生位把缺的机器人补齐：
已有单元保持原顺序和 ``unit_id``（任务里的 ``air_unit``/``scout_unit`` 仍然有效），
新增单元用 ``类-编号`` 命名，例如 ``UGV-04``、``PLANE-35``。

用法（在 planning_middle_demo 目录）：
    python -m interop.tools.full_roster            # 补齐 interop/scenarios 下全部编成表
    python -m interop.tools.full_roster --check    # 只检查，不写文件
"""

import argparse
import json
import os
from typing import Any, Dict, List, Optional

from interop.sdf_scene import build_fleet, parse_sdf

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SDF_PATH = os.path.join(os.path.dirname(BASE_DIR), "资料", "接口说明",
                        "container_00_combined_scene.sdf")
SCENARIO_DIR = os.path.join(BASE_DIR, "interop", "scenarios")


def append_full_roster(formation: Dict[str, Any], scene,
                       total: Optional[int] = None) -> int:
    """就地补齐编成表，返回新增平台数；已补齐时返回 0。"""
    units: List[Dict[str, Any]] = formation.setdefault("units", [])
    limit = int(total or len(scene.robots))
    used = {int(u["robot_id"]) for u in units if u.get("robot_id") is not None}
    missing = [no for no in range(1, limit + 1) if no not in used]

    extra: List[Dict[str, Any]] = []
    if missing:
        extra = build_fleet(
            scene, missing,
            plan_id=formation.get("formation_id") or "PLAN-INTEROP-001"
        )["formation"]["units"]
        ids = {u["unit_id"] for u in units}
        for unit in extra:
            candidate = "%s-%02d" % (unit["platform_class"], unit["robot_id"])
            suffix = 2
            while candidate in ids:
                candidate = "%s-%02d-%d" % (unit["platform_class"],
                                            unit["robot_id"], suffix)
                suffix += 1
            unit["unit_id"] = candidate
            ids.add(candidate)
        units.extend(extra)

    # 补齐后统一速度口径；已有的全编成表再次运行也会被校正。
    normalize_speeds(formation)
    meta = formation.setdefault("meta", {})
    meta["roster_total"] = len(units)
    meta["roster_source"] = "container_00_combined_scene.sdf（按出生位全编成）"
    return len(extra)


def normalize_speeds(formation: Dict[str, Any]) -> None:
    """补齐平台的速度跟本编成表的既有口径一致。

    SDF 场景速度是场景单位/秒（UGV 8、PLANE 30…），手写编成表有的用米/秒
    （asl_junction 是 0.8/2.0）。同一作业里两种口径混用，会让规划按 8 m/s
    估时、行为层按 8 m/s 去跟密集航点，平台原地打转。这里先看基准平台用
    哪套口径：基准是米/秒就按同类基准速度补；基准是场景单位就恢复 SDF 的
    默认类速度。
    """
    import re
    from interop.sdf_scene import CLASS_PARAMS

    ours = re.compile(r"^(UGV|TANK|PLANE|WING)-\d")
    base = [u for u in formation.get("units", [])
            if not ours.match(str(u.get("unit_id")))
            and u.get("speed_mps") is not None]
    if not base:
        return
    metric = max(float(u["speed_mps"]) for u in base) <= 3.0
    peers: Dict[str, List[float]] = {}
    for unit in base:
        peers.setdefault(unit.get("platform_class"), []).append(
            float(unit["speed_mps"]))
    for unit in formation.get("units", []):
        if not ours.match(str(unit.get("unit_id"))):
            continue
        kind = unit.get("platform_class")
        if metric:
            candidates = peers.get(kind) or []
            if candidates:
                unit["speed_mps"] = float(candidates[0])
        elif kind in CLASS_PARAMS:
            unit["speed_mps"] = float(CLASS_PARAMS[kind]["speed_mps"])


def apply_to_file(path: str, scene, total: Optional[int] = None,
                  check_only: bool = False):
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    before = json.dumps(data, ensure_ascii=False, sort_keys=True)
    formation = data.get("formation") or {}
    added = append_full_roster(formation, scene, total=total)
    changed = before != json.dumps(data, ensure_ascii=False, sort_keys=True)
    if changed and not check_only:
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
    return added, changed


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="把 SDF 全部平台并入编成表")
    parser.add_argument("--sdf", default=SDF_PATH)
    parser.add_argument("--dir", default=SCENARIO_DIR)
    parser.add_argument("--check", action="store_true",
                        help="只检查缺口，不写文件")
    args = parser.parse_args(argv)

    scene = parse_sdf(args.sdf)
    total = len(scene.robots)
    names = sorted(n for n in os.listdir(args.dir) if n.endswith(".formation.json"))
    if not names:
        raise SystemExit("没有找到编成表：%s" % args.dir)

    changed = 0
    for name in names:
        path = os.path.join(args.dir, name)
        added, touched = apply_to_file(path, scene, total=total,
                                       check_only=args.check)
        with open(path, encoding="utf-8") as fh:
            units = len((json.load(fh).get("formation") or {}).get("units") or [])
        if added:
            note = "补齐 %d 台" % added
        elif touched:
            note = "已完整，校正速度/元数据"
        else:
            note = "已完整"
        print("%-38s units=%d  %s" % (name, units, note))
        changed += 1 if (added or touched) else 0
    verb = "待处理" if args.check else "已处理"
    print("%s：%d/%d 个编成表，SDF 平台总数=%d" % (verb, changed, len(names), total))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
