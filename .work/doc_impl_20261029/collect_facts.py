import json
from pathlib import Path

base = Path(r"D:\Desktop\MARL项目\planning_middle_demo")
for name in ("workbench_20261029_181813_611337", "asl_city_suppress", "asl_city_seize"):
    run = base / "outputs" / name
    report = json.loads((run / "report.json").read_text(encoding="utf-8"))
    print("=" * 30, name)
    print("sim", report["simulated_until_s"], "done", report["done"], "settled", report["settled"],
          "energy", report.get("used_energy"), "plans", report.get("plans"),
          "retries", report.get("retries"), "timeouts", report.get("timeouts"),
          "limit_reached", report.get("limit_reached"))
    print("rejected", report.get("rejected_reasons"))
    print("job", {k: report["jobs"][0].get(k) for k in ("job_id", "status", "attempts", "progress", "started_at", "planned_end")})
    events = {}
    for line in (run / "trace.jsonl").read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        if row.get("kind") == "behavior_event":
            ev = row["event"]
            events.setdefault(ev.get("kind"), []).append((row["sim_s"], ev))
    for key in ("command_received", "all_staged", "assault_started", "effect_started",
                "effect_achieved", "effect_applied", "assessment_requested",
                "assessment_received", "confirmed", "withdraw_started", "withdrawn", "behavior_result"):
        rows = events.get(key) or []
        print("  %-22s %s" % (key, rows[0][0] if rows else None))
    result = (events.get("behavior_result") or [{}])[-1]
    if result:
        ev = result[1]
        print("  result", ev.get("overall"), ev.get("termination"), ev.get("adjudicator"), ev.get("verified"))
        for row in ev.get("auxiliary") or []:
            print("    aux:", row["label"], row["value"], row["unit"], row["verdict"])
        print("    role_check", ev.get("role_check"))
    print()
