from pathlib import Path
import sys, json, io, time, subprocess, unittest, copy, hashlib
ROOT=Path(r"C:\Users\ammo\Desktop\MARL项目")
OUT=ROOT/"outputs"/"planning_middle_demo指标核查_20261027"
SRC=OUT/"snapshot"/"planning_middle_demo"
sys.path.insert(0,str(SRC))
log=io.StringIO()
suite=unittest.defaultTestLoader.discover(str(SRC/"tests"))
t0=time.perf_counter()
result=unittest.TextTestRunner(stream=log,verbosity=2).run(suite)
(OUT/"baseline_tests.txt").write_text(log.getvalue(),encoding="utf-8")
summary={"python":sys.version,"test_count":result.testsRun,"failures":len(result.failures),"errors":len(result.errors),"skipped":len(result.skipped),"elapsed_s":round(time.perf_counter()-t0,3)}
runs=[]
for name,extra in [
    ("normal",["--mode","normal"]),("failure",["--mode","failure"]),
    ("timeout",["--mode","timeout"]),("kill",["--mode","kill"]),
    ("deviation",["--mode","deviation"]),
    ("motion",["--mode","normal","--motion","real","--max-ticks","150"])]:
    dest=OUT/"runs"/name
    cmd=[sys.executable,"-B",str(SRC/"run_demo_v2.py"),*extra,"--out",str(dest),"--quiet"]
    run=subprocess.run(cmd,capture_output=True,text=True,encoding="utf-8",errors="replace",timeout=40)
    (OUT/(name+"_cli.txt")).write_text(run.stdout+"\n"+run.stderr,encoding="utf-8")
    data=json.loads((dest/"report.json").read_text(encoding="utf-8")) if (dest/"report.json").exists() else {}
    runs.append({"name":name,"exit_code":run.returncode,**{k:data.get(k) for k in ("done","all_succeeded","settled","active_commands","retries","timeouts","limit_reached","simulated_until_s")}})
from contracts_v2 import check_scenario_v2
from coordinator_v2 import CoordinatorV2
from mock_fleet import MockFleet
def generic():
    return {"protocol":"middle-demo/v2","platforms":[{"robot_no":1,"pos":[0,0]}],
            "jobs":[{"job_id":"ordinary-job","pos":[0,0],"work":2.0,"window":[0,50],"crew":1,"need_payload":0,"need_sensor":None,"altitude":0}]}
def started():
    core=CoordinatorV2(generic())
    peer=MockFleet()
    messages=core.step(0)
    replies=peer.submit(messages,0)
    return core,peer,messages,replies[0]
probes=[]
core,peer,msg,event=started()
initial=list(core.platforms["rover_01"].pos)
bad=copy.deepcopy(event);bad.update(event_id="audit-invalid-battery",pos=[123.0,456.0],battery=-1)
accepted=core.receive(bad,0)
probes.append({"id":"Q1","name":"rejected_feedback_atomicity","accepted":accepted,"before_pos":initial,"after_pos":list(core.platforms["rover_01"].pos),"violation":not accepted and list(core.platforms["rover_01"].pos)!=initial})
core,peer,msg,event=started()
bad=copy.deepcopy(event);bad.update(event_id="audit-nonfinite",progress=float("nan"))
accepted=core.receive(bad,0)
probes.append({"id":"Q2","name":"nonfinite_feedback","accepted":accepted,"stored_progress":repr(core.cmd_progress.get(msg[0]["command"]["command_id"])),"violation":accepted})
for label,edit in [
    ("unknown_root",lambda s:s.update(timline=[])),
    ("negative_work",lambda s:s["jobs"][0].update(work=-1)),
    ("zero_crew",lambda s:s["jobs"][0].update(crew=0)),
    ("fractional_crew",lambda s:s["jobs"][0].update(crew=1.5)),
    ("nan_rule",lambda s:s.update(rules={"dev_threshold":float("nan")})),
]:
    s=generic();edit(s)
    try:check_scenario_v2(s);accepted=True;err=None
    except Exception as exc:accepted=False;err=type(exc).__name__
    probes.append({"id":"Q3","name":label,"accepted_by_validator":accepted,"error_type":err})
core,peer,msg,event=started()
probes.append({"id":"Q4","name":"plan_version_correlation","plan_id":core.plan.plan_id,"wire_plan_id":msg[0]["plan_id"],"violation":core.plan.plan_id!=msg[0]["plan_id"]})
core_a,peer_a,msg_a,event_a=started()
core_b,peer_b,msg_b,event_b=started()
old=copy.deepcopy(event_a);old["event_id"]="audit-from-previous-run"
accepted=core_b.receive(old,0)
probes.append({"id":"Q5","name":"default_run_identity_collision","same_run_id":core_a.run_id==core_b.run_id,"same_command_id":msg_a[0]["command"]["command_id"]==msg_b[0]["command"]["command_id"],"previous_run_feedback_accepted":accepted})
# Inspect the CLI's effective configuration recording using an ordinary job only.
s=generic();s["rules"]={"max_attempts":3,"dev_threshold":7,"grace_s":5}
cfg=OUT/"ordinary_rules_probe.json";cfg.write_text(json.dumps(s),encoding="utf-8")
dest=OUT/"runs"/"rules_record"
run=subprocess.run([sys.executable,"-B",str(SRC/"run_demo_v2.py"),"--scenario",str(cfg),"--out",str(dest),"--quiet"],capture_output=True,text=True,encoding="utf-8",errors="replace",timeout=30)
man=json.loads((dest/"manifest.json").read_text(encoding="utf-8"))
rep=json.loads((dest/"report.json").read_text(encoding="utf-8"))
probes.append({"id":"Q6","name":"effective_configuration_record","manifest":{k:man[k] for k in ("max_attempts","dev_threshold","grace_s")},"scenario_rules":rep["rules"],"violation":man["max_attempts"]!=rep["rules"]["max_attempts"]})
manifest=json.loads((OUT/"source_manifest.json").read_text(encoding="utf-8"))
changed=[]
for f in manifest["files"]:
    p=ROOT/"planning_middle_demo"/f["path"]
    if not p.exists() or hashlib.sha256(p.read_bytes()).hexdigest()!=f["sha256"]:changed.append(f["path"])
all_results={"baseline":summary,"runs":runs,"generic_software_probes":probes,"source_changes_since_snapshot":changed,"scope":"Existing scenarios and generic message/configuration checks only; no business-code modifications; no external integration or tactical-effectiveness testing."}
(OUT/"audit_results.json").write_text(json.dumps(all_results,ensure_ascii=False,indent=2,allow_nan=False),encoding="utf-8")
print(json.dumps(all_results,ensure_ascii=False,indent=2))

