# -*- coding: utf-8 -*-
"""Capture and export an auditable run chain from commands through feedback."""

from copy import deepcopy
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import html
import json
from pathlib import Path
import time


ARCHIVE_FILES = (
    "scenario_snapshot.json",
    "platform_snapshot.json",
    "group_history.jsonl",
    "task_history.jsonl",
    "subtask_history.jsonl",
    "commands.jsonl",
    "feedback.jsonl",
    "change_events.jsonl",
    "report.json",
    "manifest.json",
)


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2),
                          encoding="utf-8")


def _write_jsonl(path, rows):
    Path(path).write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8")


def _read_jsonl(path):
    return [json.loads(line) for line in Path(path).read_text(
        encoding="utf-8").splitlines() if line.strip()]


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class ChainRecorder:
    """Observe actual coordinator messages without changing their contents."""

    def __init__(self, message, formation, planner=None):
        self.message = deepcopy(message)
        self.formation = deepcopy(formation)
        self.planner = planner
        self.started_utc = utc_now()
        self.finished_utc = None
        self.commands = []
        self.feedback = []
        self.config_events = []
        self.planning = []
        self.command_rows = {}
        self.attached = False
        self.group_version = 1
        self.motion = None

    def before_tick(self, core, fleet, now):
        if not self.attached:
            self.attach(core, fleet)

    def attach(self, core, fleet):
        if self.attached:
            return
        self.attached = True
        if fleet.motion == 'real':
            from interop.motion_replay import MotionReplay, sdf_drive_limits
            import fleet as fleet_ids
            units = {fleet_ids.pid_of(u['robot_id']):u['unit_id'] for u in self.formation['formation']['units']}
            meta = self.formation.get('meta') or {}
            self.motion = MotionReplay(core.platforms, units, meta.get('cell_size_m',1.0),sdf_drive_limits(meta))
            fleet.motion_recorder = self.motion.record
        submit = fleet.submit
        receive = core.receive
        record = core.record
        replan = core._replan

        def submit_hook(messages, now):
            rows = [self._command(core, wire, now) for wire in messages]
            events = submit(messages, now)
            stamp = utc_now()
            for row in rows:
                row["submitted_utc"] = stamp
                self.command_rows[row["command_id"]] = row
                self.commands.append(row)
            return events

        def receive_hook(event, now):
            received = utc_now()
            accepted = receive(event, now)
            processed = utc_now()
            if isinstance(event, dict) and event.get("command_id"):
                command = self.command_rows.get(event["command_id"])
                reason = None
                if not accepted and core.audit:
                    last = core.audit[-1]
                    if last.get("kind") == "feedback_ignored":
                        reason = last.get("reason")
                pid = event.get("worker_id")
                self.feedback.append(dict(
                    run_id=core.run_id,
                    event_id=event.get("event_id"),
                    command_id=event.get("command_id"),
                    task_id=event.get("job_id"),
                    subtask_id=(command or {}).get("subtask_id"),
                    attempt_id="%s:a%s" % (event.get("job_id"),
                                           event.get("attempt")),
                    attempt=event.get("attempt"),
                    unit_id=(command or {}).get("unit_id"),
                    worker_id=pid,
                    robot_id=(command or {}).get("robot_id"),
                    status=event.get("status"),
                    progress=event.get("progress"),
                    subtask_progress=event.get("subtask_progress"),
                    phase=event.get("phase"),
                    sim_s=event.get("sim_s"),
                    pos=event.get("pos"),
                    z=event.get("z"),
                    yaw=event.get("yaw"),
                    battery=event.get("battery"),
                    note=event.get("note"),
                    accepted=bool(accepted),
                    reject_reason=reason,
                    received_utc=received,
                    processed_utc=processed,
                ))
            return accepted

        def record_hook(kind, **fields):
            record(kind, **fields)
            if kind == "config_updated":
                if self.motion is not None:
                    import fleet as fleet_ids
                    for unit in (fields.get('formation') or {}).get('formation', {}).get('units', []):
                        self.motion.units[fleet_ids.pid_of(unit['robot_id'])] = unit['unit_id']
                if (fields.get("added_platforms") or fields.get("removed_platforms")
                        or fields.get("platforms")):
                    self.group_version += 1
                stamp = utc_now()
                self.config_events.append(dict(
                    kind="config_updated",
                    sim_s=core.now,
                    source=fields.get("source", "config_updated"),
                    message=deepcopy(fields.get("message") or self.message),
                    formation=deepcopy(fields.get("formation") or self.formation),
                    tasks=deepcopy(fields.get("tasks") or []),
                    added=deepcopy(fields.get("added_platforms") or []),
                    removed=deepcopy(fields.get("removed_platforms") or []),
                    modified=deepcopy(fields.get("platforms") or []),
                    group_version="g%d" % self.group_version,
                    received_utc=stamp,
                    processed_utc=stamp,
                ))

        def replan_hook(now):
            started = time.perf_counter()
            replan(now)
            self.planning.append(dict(
                sim_s=now,
                plan_id=getattr(core.plan, "plan_id", None),
                elapsed_ms=round((time.perf_counter() - started) * 1000, 3),
            ))

        fleet.submit = submit_hook
        core.receive = receive_hook
        core.record = record_hook
        core._replan = replan_hook

    def _planned_subtask(self, plan_id, task_id, robot_id):
        if self.planner is None or not getattr(self.planner, "plan_history", None):
            return {}
        version = next((row for row in reversed(self.planner.plan_history)
                        if row.get("runtime_plan_id") == plan_id), None)
        if not version:
            return {}
        assignments = (version.get("plan") or {}).get("assignments") or []
        return next((row for row in assignments
                     if row.get("parent_task_id") == task_id
                     and row.get("robot_id") == robot_id), {})

    def _command(self, core, wire, now):
        command = wire["command"]
        cid = command["command_id"]
        plan_id = wire.get("plan_id")
        pid = command["worker_id"]
        platform = core.platforms.get(pid)
        robot_id = platform.robot_no if platform else None
        assignment = self._planned_subtask(plan_id, command["job_id"], robot_id)
        subtask_id = core.subtask_commands.get(cid) or assignment.get("subtask_id")
        state = core.subtask_states.get(subtask_id,{})
        if subtask_id is None and command.get("target_command_id"):
            original = self.command_rows.get(command["target_command_id"])
            subtask_id = (original or {}).get("subtask_id")
        return dict(
            run_id=wire["run_id"],
            command_id=cid,
            plan_id=plan_id,
            config_version="v%d" % (1 + len(self.config_events)),
            group_version="g%d" % self.group_version,
            task_id=command["job_id"],
            attempt_id="%s:a%d" % (command["job_id"], command["attempt"]),
            attempt=command["attempt"],
            subtask_id=subtask_id,
            role=state.get("role") or assignment.get("role"),
            unit_id=(assignment.get("unit_id")
                     or next((u["unit_id"] for u in (self.config_events[-1]["formation"] if self.config_events else self.formation)["formation"]["units"] if u["robot_id"]==robot_id),None)
                     or (platform.unit_id if hasattr(platform, "unit_id") else None)),
            worker_id=pid,
            robot_id=robot_id,
            topic=platform.topic if platform else None,
            action=command.get("action") or "start",
            target_command_id=command.get("target_command_id"),
            issued_sim_s=command["issued_sim_s"],
            start_sim_s=command["start_sim_s"],
            expected_end_sim_s=command["expected_end_sim_s"],
            dispatched_sim_s=now,
            task=deepcopy(command.get("task") or {}),
            delivery=deepcopy(command.get("delivery") or {}),
            issued_utc=utc_now(),
            submitted_utc=None,
        )


def _window(task):
    if isinstance(task.get("window"), dict):
        return deepcopy(task["window"])
    return dict(start_s=task.get("window_start_s", 0),
                end_s=task.get("window_end_s", 0))


def _task_type(task):
    return task.get("task_type") or task.get("type") or ""


def _subtasks(scenario):
    if isinstance(scenario, tuple):
        from interop.message import parse_message
        scenario = parse_message(scenario[0], scenario[1], allow_empty_tasks=True)
    from interop.templates import decompose
    return [asdict(item) for item in decompose(scenario)]


def _command_status(feedback, command_id):
    rows = [row for row in feedback if row.get("command_id") == command_id
            and row.get("accepted")]
    return rows[-1].get("status") if rows else None


def _build_archive(out, recorder, scenario, initial_message, initial_formation,
                   report, audit, label):
    archive = out / "archive"
    archive.mkdir(parents=True, exist_ok=True)
    tasks = initial_message.get("tasks") or []
    task_by_id = {row["task_id"]: row for row in tasks}
    slots = _subtasks(scenario)
    slot_versions = [('v1', 'g1', 0, _subtasks((initial_message, initial_formation)))]
    for index, event in enumerate(recorder.config_events, start=2):
        slot_versions.append(('v%d' % index, event['group_version'], event['sim_s'],
                              _subtasks((event['message'], event['formation']))))
    jobs = {row["job_id"]: row for row in report.get("jobs") or []}
    slot_status = {}
    for slot in slots:
        commands = [row for row in recorder.commands
                    if row.get("subtask_id") == slot["subtask_id"]
                    and row.get("action") == "start"]
        states = [_command_status(recorder.feedback, row["command_id"])
                  for row in commands]
        if "succeeded" in states:
            status = "succeeded"
        elif "failed" in states:
            status = "failed"
        elif commands:
            status = "in_progress"
        else:
            status = "unassigned"
        slot_status[slot["subtask_id"]] = status

    scenario_snapshot = dict(
        run_id=report["run_id"],
        case_key=label,
        label=label,
        message_id=initial_message.get("message_id"),
        issued_at=initial_message.get("issued_at"),
        source=initial_message.get("source"),
        coordinate_frame="场景坐标；时间单位为仿真秒",
        counts=dict(tasks=len(tasks), platforms=len(scenario.platforms),
                    slots=len(slots)),
        task_ids=list(task_by_id),
        task_relations=[dict(
            task_id=task_id,
            depends_on=list(task.get("depends_on") or []),
            relation=("PARALLEL" if not task.get("depends_on")
                      else "SEQUENTIAL" if len(task.get("depends_on")) == 1
                      else "CONVERGE"),
        ) for task_id, task in task_by_id.items()],
        version_index=[dict(config_version="v1", group_version="g1",
                            sim_s=0, reason="初始加载")] + [dict(
            config_version="v%d" % (index + 2),
            group_version=event["group_version"],
            sim_s=event["sim_s"], reason=event["source"])
            for index, event in enumerate(recorder.config_events)],
        source_files=dict(
            message_sha256=hashlib.sha256(json.dumps(
                initial_message, ensure_ascii=False,
                sort_keys=True).encode()).hexdigest(),
            formation_sha256=hashlib.sha256(json.dumps(
                initial_formation, ensure_ascii=False,
                sort_keys=True).encode()).hexdigest(),
        ),
    )

    units = ((initial_formation.get("formation") or {}).get("units") or [])
    final_platforms = {row.get("pid"): row for row in report.get("platforms") or []}
    from fleet import pid_of, topic_of
    platform_rows = []
    for unit in units:
        state = final_platforms.get(pid_of(unit["robot_id"])) or {}
        platform_rows.append(dict(
            unit_id=unit.get("unit_id"),
            robot_id=unit.get("robot_id"),
            pid=pid_of(unit["robot_id"]),
            topic=topic_of(unit["robot_id"]),
            platform_class=unit.get("platform_class"),
            platform_type=unit.get("platform_type"),
            position=deepcopy(unit.get("position")),
            altitude_m=unit.get("altitude_m", 0),
            heading_rad=unit.get("heading_rad", 0),
            status=unit.get("status", "READY"),
            final=dict(
                alive=state.get("alive"),
                position=state.get("pos"),
                battery=state.get("battery"),
                return_status=state.get("return_status"),
            ),
        ))
    platform_snapshot = dict(run_id=report["run_id"], count=len(platform_rows),
                             platforms=platform_rows)

    groups = [dict(
        run_id=report["run_id"], group_version="g1", config_version="v1",
        sim_s=0, reason="初始编成", added=[], removed=[], modified=[],
        units=platform_rows,
    )]
    for index, event in enumerate(recorder.config_events, start=2):
        units_after = (((event.get("formation") or {}).get("formation") or {})
                       .get("units") or units)
        groups.append(dict(
            run_id=report["run_id"],
            group_version=event["group_version"],
            config_version="v%d" % index,
            sim_s=event["sim_s"],
            reason=event["source"],
            added=event.get("added") or [],
            removed=event.get("removed") or [],
            modified=event.get("modified") or [],
            units=deepcopy(units_after),
        ))

    task_rows = []
    for task_id, task in task_by_id.items():
        task_rows.append(dict(
            run_id=report["run_id"], task_id=task_id, task_version="v1",
            action="ADD", config_version="v1", group_version="g1", sim_s=0,
            changed_fields=["*"], before=None, after=deepcopy(task),
            target=deepcopy(task.get("target")), window=_window(task),
            depends_on=list(task.get("depends_on") or []),
            relation=("PARALLEL" if not task.get("depends_on")
                      else "SEQUENTIAL" if len(task.get("depends_on")) == 1
                      else "CONVERGE"),
        ))
    for task_id, job in jobs.items():
        task_rows.append(dict(
            run_id=report["run_id"], task_id=task_id, task_version="v1",
            action="STATUS", config_version=scenario_snapshot["version_index"][-1]["config_version"],
            group_version=scenario_snapshot["version_index"][-1]["group_version"],
            sim_s=report["simulated_until_s"], status=job.get("status"),
            attempts=job.get("attempts"), progress=job.get("progress"),
            work=job.get("work"),
        ))
    attempts = {}
    for command in recorder.commands:
        if command.get("action") == "start":
            attempts.setdefault((command["task_id"], command["attempt"]), []).append(command)
    for (task_id, attempt), commands in sorted(attempts.items()):
        feedback = [row for row in recorder.feedback
                    if row.get("task_id") == task_id and row.get("attempt") == attempt]
        task_rows.append(dict(
            run_id=report["run_id"], task_id=task_id, task_version="v1",
            action="ATTEMPT", attempt_id="%s:a%d" % (task_id, attempt),
            attempt=attempt, config_version=commands[0]["config_version"],
            group_version=commands[0]["group_version"],
            sim_s=commands[0]["dispatched_sim_s"],
            command_ids=[row["command_id"] for row in commands],
            subtask_ids=sorted({row["subtask_id"] for row in commands
                                if row.get("subtask_id")}),
            outcome=feedback[-1].get("status") if feedback else "unknown",
        ))
    task_rows.sort(key=lambda row: (row["sim_s"], row["task_id"], row["action"]))

    previous_tasks = dict(task_by_id)
    for index, event in enumerate(recorder.config_events, start=2):
        current_tasks = {task['task_id']: task for task in event['message']['tasks']}
        for task_id in sorted(previous_tasks.keys() | current_tasks.keys()):
            before, after = previous_tasks.get(task_id), current_tasks.get(task_id)
            if before == after:
                continue
            task_rows.append(dict(run_id=report['run_id'], task_id=task_id,
                task_version='v%d' % index, config_version='v%d' % index,
                group_version=event['group_version'], sim_s=event['sim_s'],
                action='ADD' if before is None else 'DELETE' if after is None else 'MODIFY',
                changed_fields=sorted(key for key in (before or {}).keys() | (after or {}).keys()
                                      if (before or {}).get(key) != (after or {}).get(key)),
                before=deepcopy(before), after=deepcopy(after)))
        previous_tasks = current_tasks

    task_rows.sort(key=lambda row: (row['sim_s'], row['task_id'], row['action']))

    subtask_rows = [dict(
        run_id=report["run_id"],
        at_s=at_s, task_id=row["parent_task_id"], task_version=version,
        subtask_id=row["subtask_id"], index=row["index"],
        config_version=version, group_version=group, sim_s=at_s,
        role=row.get("role") or "", task_type=row["task_type"],
        target=row["target"], duration_s=row["duration_s"],
        window=dict(start_s=row["window_start_s"], end_s=row["window_end_s"]),
        depends_on_subtasks=list(row.get("depends_on") or []),
        coordination=list(row.get("coordination") or []),
        pinned_unit=row.get("pinned_unit") or None,
        status=slot_status.get(row["subtask_id"], "unassigned"),
    ) for version, group, at_s, version_slots in slot_versions for row in version_slots]

    commands = sorted(deepcopy(recorder.commands),
                      key=lambda row: (row["dispatched_sim_s"], row["command_id"]))
    feedback = sorted(deepcopy(recorder.feedback),
                      key=lambda row: (row.get("sim_s") or -1,
                                       row.get("received_utc") or ""))
    for row in feedback:
        command = next((item for item in commands
                        if item["command_id"] == row["command_id"]), {})
        row.setdefault("plan_id", command.get("plan_id"))
        row.setdefault("config_version", command.get("config_version"))
        row.setdefault("group_version", command.get("group_version"))

    changes = []
    for index, event in enumerate(recorder.config_events, start=1):
        changes.append(dict(
            run_id=report["run_id"], event_id="CE-%02d" % index,
            kind="CONFIG_UPDATED", source=event.get("source", "config_updated"),
            sim_s=event["sim_s"], received_utc=event.get("received_utc"),
            processed_utc=event.get("processed_utc"),
            config_version_before="v%d" % index,
            config_version_after="v%d" % (index + 1),
            group_version_before=("g1" if index == 1
                                  else recorder.config_events[index - 2]["group_version"]),
            group_version_after=event["group_version"],
            task_id=event.get("task_id"),
            robot_id=event.get("robot_id"),
            effect_observed_sim_s=event["sim_s"],
            observed_handling="config_applied",
            detail=event,
        ))
    timeline_kind = {
        "timeout": "TASK_TIMEOUT",
        "member_lost": "PLATFORM_LOST",
        "job_failed": "TASK_FAIL",
        "subtask_failed": "TASK_FAIL",
        "run_stopped": "RUN_STOPPED",
    }
    for row in audit:
        kind = timeline_kind.get(row.get("kind"))
        detail = row.get("event") or row
        if (row.get("kind") == "feedback_applied"
                and str((row.get("event") or {}).get("status")).lower() == "failed"):
            kind = "TASK_FAIL"
        if not kind:
            continue
        changes.append(dict(
            run_id=report["run_id"],
            event_id="TL-%03d" % (len(changes) + 1),
            kind=kind,
            source="timeline",
            sim_s=row["sim_s"],
            config_version_before=scenario_snapshot["version_index"][-1]["config_version"],
            config_version_after=scenario_snapshot["version_index"][-1]["config_version"],
            group_version_before=scenario_snapshot["version_index"][-1]["group_version"],
            group_version_after=scenario_snapshot["version_index"][-1]["group_version"],
            task_id=detail.get("job_id"),
            robot_id=(final_platforms.get(detail.get("worker_id") or detail.get("pid"))
                      or {}).get("robot_no"),
            effect_observed_sim_s=row["sim_s"],
            observed_handling=row.get("kind"),
            observed_reason=detail.get("reason") or detail.get("note"),
            detail=deepcopy(detail),
        ))
    changes.sort(key=lambda row: (row["sim_s"], row["event_id"]))

    archive_report = dict(
        run_id=report["run_id"], case_key=label, label=label,
        generated_at=utc_now(), simulated_until_s=report["simulated_until_s"],
        simulated=True, backend="mock_only", external_integration_verified=False,
        config_version_final=scenario_snapshot["version_index"][-1]["config_version"],
        group_version_final=scenario_snapshot["version_index"][-1]["group_version"],
        config_versions=len(scenario_snapshot["version_index"]),
        group_versions=len(groups),
        tasks=dict(ids=sorted(task_by_id),
                   succeeded=sum(job.get("status") == "succeeded"
                                 for job in jobs.values()),
                   failed=sum(job.get("status") == "failed"
                              for job in jobs.values()),
                   attempts=sum(job.get("attempts") or 0 for job in jobs.values())),
        platforms=dict(initial=len(units),
                       final=len(report.get("platforms") or []),
                       lost=sum(not item.get("alive")
                                for item in report.get("platforms") or [])),
        subtasks=dict(
            final_snapshot=len(slots),
            succeeded=sum(value == "succeeded" for value in slot_status.values()),
            failed=sum(value == "failed" for value in slot_status.values()),
            unassigned=sum(value == "unassigned" for value in slot_status.values()),
        ),
        commands=dict(total=len(commands),
                      starts=sum(row.get("action") == "start" for row in commands),
                      cancels=sum(row.get("action") == "cancel" for row in commands)),
        feedback=dict(total=len(feedback),
                      accepted=sum(bool(row.get("accepted")) for row in feedback),
                      rejected=sum(not row.get("accepted") for row in feedback)),
        change_events=dict(total=len(changes)),
        settled=report.get("settled"), all_succeeded=report.get("all_succeeded"),
        manual_stopped=bool(report.get('manual_stopped')),
        termination_reason=report.get('termination_reason','normal'),
        timing_resolution=deepcopy(report.get("timing_resolution")),
        scheduler_timing_resolution=deepcopy(report.get("scheduler_timing_resolution")),
    )

    _write_json(archive / "scenario_snapshot.json", scenario_snapshot)
    _write_json(archive / "platform_snapshot.json", platform_snapshot)
    _write_jsonl(archive / "group_history.jsonl", groups)
    _write_jsonl(archive / "task_history.jsonl", task_rows)
    _write_jsonl(archive / "subtask_history.jsonl", subtask_rows)
    _write_jsonl(archive / "commands.jsonl", commands)
    _write_jsonl(archive / "feedback.jsonl", feedback)
    _write_jsonl(archive / "change_events.jsonl", changes)
    _write_json(archive / "report.json", archive_report)
    manifest = dict(
        run_id=report["run_id"],
        generated_at=utc_now(),
        generator="planning_middle_demo/chain_trace.py",
        note="哈希覆盖除 manifest.json 外的全部归档文件。",
        files=[dict(name=name, bytes=(archive / name).stat().st_size,
                    sha256=_sha(archive / name))
               for name in ARCHIVE_FILES if name != "manifest.json"],
    )
    _write_json(archive / "manifest.json", manifest)
    raw = dict(
        run_id=report["run_id"], label=label,
        initial_message=deepcopy(initial_message),
        initial_formation=deepcopy(initial_formation),
        config_events=deepcopy(recorder.config_events),
        planning=deepcopy(recorder.planning),
        commands=commands, feedback=feedback, changes=changes,
        timing_resolution=deepcopy(report.get("timing_resolution")),
        scheduler_timing_resolution=deepcopy(report.get("scheduler_timing_resolution")),
    )
    final_message = (deepcopy(recorder.config_events[-1]["message"])
                     if recorder.config_events else deepcopy(initial_message))
    final_formation = (deepcopy(recorder.config_events[-1]["formation"])
                       if recorder.config_events else deepcopy(initial_formation))
    _write_json(out / "initial_config.json", dict(
        message=initial_message, formation=initial_formation))
    _write_json(out / "final_config.json", dict(
        message=final_message, formation=final_formation))
    _write_json(out / "chain_raw.json", raw)
    return archive


def verify_chain(out):
    archive = Path(out) / "archive"
    checks = []

    def add(cid, name, failures, total=0):
        checks.append(dict(id=cid, name=name, passed=not failures,
                           total=total, failed=len(failures),
                           details=failures[:10]))

    missing = [name for name in ARCHIVE_FILES
               if not (archive / name).is_file()]
    add("C1", "归档文件齐全", missing, len(ARCHIVE_FILES))
    if missing:
        result = dict(passed=False, checks=checks)
        _write_json(Path(out) / "chain_verification.json", result)
        return result

    scenario = json.loads((archive / "scenario_snapshot.json").read_text(encoding="utf-8"))
    platforms = json.loads((archive / "platform_snapshot.json").read_text(
        encoding="utf-8"))
    tasks = _read_jsonl(archive / "task_history.jsonl")
    subtasks = _read_jsonl(archive / "subtask_history.jsonl")
    commands = _read_jsonl(archive / "commands.jsonl")
    feedback = _read_jsonl(archive / "feedback.jsonl")
    changes = _read_jsonl(archive / "change_events.jsonl")
    raw_path = Path(out) / "chain_raw.json"
    raw = (json.loads(raw_path.read_text(encoding="utf-8"))
           if raw_path.is_file() else {})
    task_ids = {row["task_id"] for row in tasks}
    subtask_ids = {row["subtask_id"] for row in subtasks}
    command_by_id = {row["command_id"]: row for row in commands}
    config_versions = {
        row["config_version"] for row in scenario.get("version_index") or []
    }
    group_versions = {
        row["group_version"] for row in scenario.get("version_index") or []
    }
    platform_by_pid = {
        row["pid"]: row for row in platforms.get("platforms") or []
        if row.get("pid") is not None
    }
    planning_ids = {
        row.get("plan_id") for row in raw.get("planning") or []
        if row.get("plan_id") is not None
    }

    failures = [row["command_id"] for row in commands
                if row.get("task_id") not in task_ids
                or (row.get("action") == "start"
                    and row.get("subtask_id") not in subtask_ids)
                or row.get("attempt_id")
                != "%s:a%d" % (row.get("task_id"), row.get("attempt"))
                or row.get("config_version") not in config_versions
                or row.get("group_version") not in group_versions
                or (row.get("worker_id") in platform_by_pid
                    and platform_by_pid[row["worker_id"]].get("robot_id")
                    != row.get("robot_id"))
                or (planning_ids and row.get("plan_id") not in planning_ids)]
    add("C2", "指令可回溯到任务与子任务", failures, len(commands))

    failures = [row.get("event_id") for row in feedback
                if row.get("command_id") not in command_by_id
                or row.get("task_id") != command_by_id[row["command_id"]].get("task_id")
                or row.get("worker_id") != command_by_id[row["command_id"]].get("worker_id")
                or row.get("attempt") != command_by_id[row["command_id"]].get("attempt")]
    failures += [row.get("event_id") for row in feedback
                 if row.get("command_id") in command_by_id
                 and command_by_id[row["command_id"]].get("action") == "start"
                 and row.get("accepted")
                 and row.get("subtask_id")
                 != command_by_id[row["command_id"]].get("subtask_id")]
    add("C3", "反馈可回溯到指令与尝试", failures, len(feedback))

    failures = [row["command_id"] for row in commands
                if not row.get("issued_utc") or not row.get("submitted_utc")
                or row.get("issued_utc") > row["submitted_utc"]
                or row.get("dispatched_sim_s") is None]
    failures += [row.get("event_id") for row in feedback
                 if not row.get("received_utc") or not row.get("processed_utc")
                 or row.get("received_utc") > row["processed_utc"]
                 or row.get("sim_s") is None]
    add("C4", "仿真与系统时间戳齐全且顺序有效",
        failures, len(commands) + len(feedback))

    manifest = json.loads((archive / "manifest.json").read_text(encoding="utf-8"))
    failures = [row["name"] for row in manifest.get("files") or []
                if not (archive / row["name"]).is_file()
                or _sha(archive / row["name"]) != row["sha256"]]
    add("C5", "归档哈希与清单一致", failures, len(manifest.get("files") or []))

    run_id = json.loads((archive / "report.json").read_text(
        encoding="utf-8")).get("run_id")
    grouped = (
        ("场景快照", [scenario]),
        ("任务历史", tasks),
        ("子任务历史", subtasks),
        ("指令", commands),
        ("反馈", feedback),
        ("变化事件", changes),
    )
    failures = ["%s 的 run_id 不一致" % name
                for name, rows in grouped
                if any(row.get("run_id") != run_id for row in rows)]
    if scenario.get("run_id") != run_id:
        failures.append("场景快照与链路报告 run_id 不一致")
    add("C6", "run_id 与关联标识一致", failures,
        1 + sum(len(rows) for _, rows in grouped))

    integrity = dict(passed=all(row["passed"] for row in checks), checks=checks)
    result = dict(
        run_id=run_id, passed=integrity["passed"],
        failed_checks=[row["id"] for row in checks if not row["passed"]],
        stats=dict(commands=len(commands), feedback=len(feedback),
                   tasks=len(tasks), subtasks=len(subtasks),
                   changes=len(_read_jsonl(archive / "change_events.jsonl"))),
        checks=checks,
    )
    _write_json(Path(out) / "chain_verification.json", result)
    return result


def build_chain_viewer(out):
    out = Path(out)
    archive = out / "archive"
    scenario = json.loads((archive / "scenario_snapshot.json").read_text(encoding="utf-8"))
    platforms = json.loads((archive / "platform_snapshot.json").read_text(encoding="utf-8"))
    tasks = _read_jsonl(archive / "task_history.jsonl")
    subtasks = _read_jsonl(archive / "subtask_history.jsonl")
    commands = _read_jsonl(archive / "commands.jsonl")
    feedback = _read_jsonl(archive / "feedback.jsonl")
    changes = _read_jsonl(archive / "change_events.jsonl")
    report = json.loads((archive / "report.json").read_text(encoding="utf-8"))
    verification = json.loads((out / "chain_verification.json").read_text(encoding="utf-8"))
    status = {row["task_id"]: row.get("status") for row in tasks
              if row["action"] == "STATUS"}
    task_type = {}
    for row in tasks:
        if row.get("after"):
            task_type[row["task_id"]] = _task_type(row["after"])
    data = dict(
        scenario=scenario, platforms=platforms, tasks=tasks,
        subtasks=subtasks, commands=commands, feedback=feedback,
        changes=changes, report=report, status_by_task=status,
        taskType=task_type,
    )
    title = html.escape(str(report.get("label") or scenario.get("case_key")))
    passed = verification.get("passed")
    body = f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title} · 全链路追溯</title>
<style>
:root{{--ink:#1d2433;--mute:#6b7688;--line:#dde3ec;--bg:#f5f7fb;--card:#fff;--ok:#1f8a53;--bad:#c0392b;--warn:#b7791f;--accent:#2b5c8a}}
*{{box-sizing:border-box}}body{{margin:0;font:14px/1.55 "Segoe UI","Microsoft YaHei",sans-serif;color:var(--ink);background:var(--bg)}}
header{{padding:18px 24px;background:#fff;border-bottom:1px solid var(--line)}}h1{{margin:0 0 4px;font-size:20px}}
h2{{font-size:15px;margin:0 0 10px}}.sub{{color:var(--mute);font-size:12.5px}}.badge,.tag{{display:inline-block;padding:1px 7px;border-radius:10px;font-size:12px;background:#eef3f8;color:var(--accent)}}
.badge.ok,.tag.ok{{background:#e6f4ec;color:var(--ok)}}.badge.bad,.tag.bad{{background:#fdecea;color:var(--bad)}}.tag.warn{{background:#fdf3e1;color:var(--warn)}}
main{{display:grid;grid-template-columns:320px 1fr;gap:16px;padding:16px 24px 40px}}.panel{{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:14px}}
.summary{{display:grid;grid-template-columns:repeat(5,minmax(100px,1fr));gap:8px;margin:14px 24px 0}}.metric{{background:#fff;border:1px solid var(--line);border-radius:8px;padding:10px}}.metric b{{display:block;font-size:20px;color:var(--accent)}}
.event{{border-left:3px solid var(--line);padding:6px 8px;margin:6px 0;background:#fafbfd}}.event:hover{{border-left-color:var(--accent);background:#eef5fb}}
table{{border-collapse:collapse;width:100%;font-size:12.5px}}th,td{{border-bottom:1px solid var(--line);padding:6px;text-align:left;vertical-align:top}}th{{background:#f8fafc;color:var(--mute)}}
details{{border:1px solid var(--line);border-radius:6px;margin:7px 0;background:#fff}}summary{{cursor:pointer;padding:8px 10px;font-weight:600;background:#fafbfd}}summary::marker{{color:var(--accent)}}.inner{{padding:8px 12px 12px}}
.mono{{font-family:Consolas,monospace;font-size:11.5px;word-break:break-all}}.empty{{color:var(--mute);padding:10px 0}}footer{{color:var(--mute);font-size:11.5px;padding:0 24px 24px}}
@media(max-width:800px){{main{{grid-template-columns:1fr}}.summary{{grid-template-columns:1fr 1fr}}}}
</style></head><body>
<header><h1>{title}<span class="badge {'ok' if passed else 'bad'}">{'校验通过' if passed else '校验未通过'}</span></h1>
<div class="sub">run_id <span class="mono">{html.escape(scenario['run_id'])}</span> · 配置 {report['config_version_final']} · 编组 {report['group_version_final']} · 指令 {report['commands']['total']} · 反馈 {report['feedback']['total']} · 动态事件 {report['change_events']['total']}</div></header>
<section class="summary">
<div class="metric"><b>{html.escape(str((report.get("timing_resolution") or {}).get("rate_percent")))+"%" if (report.get("timing_resolution") or {}).get("rate_percent") is not None else "—"}</b>20回合内有效切换消解率</div>
<div class="metric">任务<b>{report['tasks']['succeeded']}/{len(report['tasks']['ids'])}</b></div>
<div class="metric">子任务<b>{report['subtasks']['succeeded']}/{report['subtasks']['final_snapshot']}</b></div>
<div class="metric">平台<b>{report['platforms']['initial']}</b></div>
<div class="metric">链路校验<b>{len(verification.get('checks') or [])} 项</b></div>
<div class="metric">运行状态<b>{'完成' if report.get('settled') else '未完成'}</b></div>
</section>
<main><div>
<section class="panel" style="margin-bottom:14px"><h2>动态事件与版本</h2><div id="events"></div></section>
<section class="panel"><h2>平台编成</h2><div id="platforms"></div></section>
</div><section class="panel"><h2>任务 → 子任务 → 指令 → 反馈</h2><div class="sub">20回合时序冲突指标：{('未记录，暂不判定是否达到95%阈值。')}</div><div id="chain"></div></section></main>
<footer>本页数据来自同轮运行归档。校验通过表示任务、子任务、指令和反馈的关联及哈希一致，不代表外部平台联调或全部任务成功。生成时间 {html.escape(report.get('generated_at') or '')}。</footer>
<script>
const DATA={json.dumps(data, ensure_ascii=False).replace('</','<\\/')};
const $=s=>document.querySelector(s);
function node(tag,cls,text){{const n=document.createElement(tag);if(cls)n.className=cls;if(text!=null)n.textContent=text;return n;}}
function table(headers,rows){{const t=node('table'),h=node('tr');headers.forEach(x=>h.appendChild(node('th',null,x)));t.appendChild(h);rows.forEach(values=>{{const r=node('tr');values.forEach(x=>r.appendChild(node('td',null,x==null?'—':String(x))));t.appendChild(r);}});return t;}}
function renderEvents(){{const box=$('#events');if(!DATA.changes.length){{box.appendChild(node('div','empty','本轮没有动态变更或异常事件。'));return;}}
DATA.changes.forEach(e=>{{const d=node('div','event');d.appendChild(node('b',null,e.kind+' @'+e.sim_s+'s'));d.appendChild(node('div','sub',[e.task_id&&('任务 '+e.task_id),e.robot_id&&('平台 '+e.robot_id),e.config_version_before+'→'+e.config_version_after,e.observed_reason].filter(Boolean).join(' · ')));box.appendChild(d);}});}}
function renderPlatforms(){{$('#platforms').appendChild(table(['平台','类别','初始','终态'],DATA.platforms.platforms.map(p=>[p.pid,p.platform_class,p.position?('('+p.position.x+', '+p.position.y+')'):'—',(p.final||{{}}).alive===false?'LOST':((p.final||{{}}).return_status||p.status||'—')])));}}
function renderChain(){{const box=$('#chain');const ids=[...new Set(DATA.tasks.map(t=>t.task_id))];ids.forEach(id=>{{const subs=DATA.subtasks.filter(s=>s.task_id===id),d=node('details'),s=node('summary'),st=DATA.status_by_task[id];s.appendChild(node('span','tag '+(st==='succeeded'?'ok':st==='failed'?'bad':'warn'),st||'—'));s.appendChild(document.createTextNode(' '+id+' · '+DATA.taskType[id]+' · 子任务 '+subs.length));d.appendChild(s);const inner=node('div','inner');subs.forEach(sub=>{{const sd=node('details'),ss=node('summary');const cmds=DATA.commands.filter(c=>c.task_id===id&&c.subtask_id===sub.subtask_id&&c.action==='start');ss.appendChild(node('span','tag',sub.role||'席位'));ss.appendChild(document.createTextNode(' '+sub.subtask_id+' · '+sub.duration_s+'s · 指令 '+cmds.length));sd.appendChild(ss);const si=node('div','inner');cmds.forEach(c=>{{const cd=node('details'),cs=node('summary');cs.appendChild(node('span','tag',c.attempt_id));cs.appendChild(document.createTextNode(' '+c.worker_id+' / '+c.command_id+' @'+c.dispatched_sim_s+'s'));cd.appendChild(cs);const fb=DATA.feedback.filter(f=>f.command_id===c.command_id);const ci=node('div','inner');ci.appendChild(table(['时刻','状态','任务进度','子任务进度','相位','接收','处理'],fb.map(f=>[f.sim_s,f.status+(f.accepted?'':'（未采纳）'),f.progress,f.subtask_progress,f.phase,f.received_utc,f.processed_utc])));cd.appendChild(ci);si.appendChild(cd);}});sd.appendChild(si);inner.appendChild(sd);}});d.appendChild(inner);box.appendChild(d);}});}}
renderEvents();renderPlatforms();renderChain();
</script></body></html>"""
    path = out / "chain_viewer.html"
    path.write_text(body, encoding="utf-8")
    return path


def export_chain(out, recorder, scenario, initial_message, initial_formation,
                 report, audit, label):
    out = Path(out)
    recorder.finished_utc = utc_now()
    _build_archive(out, recorder, scenario, initial_message, initial_formation,
                   report, audit, label)
    result = verify_chain(out)
    build_chain_viewer(out)
    summary = dict(
        run_id=report["run_id"],
        passed=result["passed"],
        failed_checks=result["failed_checks"],
        commands=result["stats"]["commands"],
        feedback=result["stats"]["feedback"],
        viewer="chain_viewer.html",
        timing_resolution=deepcopy(report.get("timing_resolution")),
        note="全链路校验只检查归档关联与哈希；不表示外部平台联调或任务成功。",
    )
    _write_json(out / "chain_summary.json", summary)
    return result
