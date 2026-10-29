from pathlib import Path
import json,hashlib
ROOT=Path(r"C:\Users\ammo\Desktop\MARL项目");W=ROOT/".work/platform_review_20261026";O=ROOT/"outputs/planning_middle_demo指标核查_20261027"
road=ROOT/"outputs/gazebo_assets_2026-10-26/parsed/roads.csv";b=road.read_bytes();dst=O/"snapshot/outputs/gazebo_assets_2026-10-26/parsed/roads.csv";dst.parent.mkdir(parents=True,exist_ok=True);dst.write_bytes(b)
m=json.loads((O/"source_manifest.json").read_text(encoding="utf-8"));m["external_assets"]=[{"path":str(road),"snapshot":str(dst),"sha256":hashlib.sha256(b).hexdigest(),"bytes":len(b)}];(O/"source_manifest.json").write_text(json.dumps(m,ensure_ascii=False,indent=2),encoding="utf-8")
s=(W/"audit_snapshot.py").read_text(encoding="utf-8").replace("planning_middle_demo审查_20261026","planning_middle_demo指标核查_20261027")
(W/"audit_current_20261027.py").write_bytes(s.encode("utf-8"))
p=O/"baseline_tests_20261027.txt"
if p.exists():p.rename(O/"snapshot_missing_dependency_tests.txt")
print("External road asset copied and hashed; business source unchanged.")

