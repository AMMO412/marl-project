"""Measure confirmed platform subtask switches caused by workbench edits."""
from collections import defaultdict
from math import ceil


METRIC = 'config_subtask_switch_rate_20'
CONFIRMED = {'accepted', 'progress', 'succeeded'}


def config_resolution(audit, commands, feedback, end_s, round_steps):
    """Use only workbench revisions and the command/feedback evidence they produced."""
    budget = 20
    commands_by_id = {row['command_id']: row for row in commands}
    starts = defaultdict(dict)
    cancels = defaultdict(list)
    for row in commands:
        version = row.get('config_version')
        if row['action'] == 'start':
            starts[version].setdefault(row['worker_id'], row)
        elif row['action'] == 'cancel' and row.get('target_command_id'):
            cancels[version, row['dispatched_sim_s']].append(row['target_command_id'])

    confirmed = {}
    cancelled = set()
    for row in feedback:
        if not row.get('accepted'):
            continue
        cid, status = row['command_id'], row['status']
        if status in CONFIRMED:
            confirmed.setdefault(cid, row)
        elif status == 'cancelled':
            cancelled.add(cid)

    updates = defaultdict(list)
    version = 1
    for row in audit:
        if row['kind'] != 'config_updated':
            continue
        version += 1
        if row.get('revision') is not None:
            updates[row['sim_s']].append((version, row))

    samples = []
    for tick, edits in updates.items():
        interrupted = {}
        for version, row in edits:
            if row.get('config_changed') is False:
                continue
            # Legacy traces have no boundary snapshot. Their explicit cancel
            # commands and accepted cancel feedback identify the same old jobs.
            old_ids = row.get('interrupted_commands')
            if old_ids is None:
                old_ids = [cid for cid in cancels['v%d' % (version - 1), tick]
                           if cid in cancelled]
            for cid in old_ids:
                old = commands_by_id.get(cid)
                if (old and old.get('subtask_id') and cid in confirmed
                        and confirmed[cid]['sim_s'] <= tick):
                    interrupted.setdefault(old['worker_id'], old)

        # Edits applied within one tick are committed before the next dispatch.
        final_version = edits[-1][0]
        for pid, old in interrupted.items():
            new = starts['v%d' % final_version].get(pid)
            if (not new or not new.get('subtask_id') or new['subtask_id'] == old['subtask_id']
                    or (old.get('unit_id') and new.get('unit_id')
                        and old['unit_id'] != new['unit_id'])):
                continue
            reply = confirmed.get(new['command_id'])
            if reply and reply['sim_s'] < new['dispatched_sim_s']:
                reply = None
            elapsed = reply['sim_s'] - tick if reply else None
            within_budget = elapsed is not None and 0 <= elapsed <= budget * round_steps
            status = ('resolved' if within_budget else 'expired'
                      if end_s - tick >= budget * round_steps else 'insufficient')
            samples.append(dict(
                revision=edits[-1][1]['revision'], config_version='v%d' % final_version,
                edit_s=tick, worker_id=pid, unit_id=new.get('unit_id'),
                from_subtask_id=old['subtask_id'], to_subtask_id=new['subtask_id'],
                from_command_id=old['command_id'], to_command_id=new['command_id'],
                dispatch_s=new['dispatched_sim_s'], confirmed_s=reply['sim_s'] if reply else None,
                feedback_id=reply.get('event_id') if reply else None,
                rounds_used=ceil(elapsed / round_steps) if elapsed is not None else None,
                status=status,
            ))
    eligible = [sample for sample in samples if sample['status'] != 'insufficient']
    resolved = [sample for sample in eligible if sample['status'] == 'resolved']
    total = len(eligible)
    rate = len(resolved) / total if total else None
    return dict(
        metric=METRIC, rate=None if rate is None else round(rate, 4),
        rate_percent=None if rate is None else round(rate * 100, 2),
        meets_threshold=None if rate is None else rate >= .95,
        config_edits=sum(row.get('config_changed') is not False
                         for edits in updates.values() for _, row in edits),
        resolved=len(resolved), total=total, expired=total - len(resolved),
        insufficient=len(samples) - total, budget_rounds=budget, round_steps=round_steps,
        by_round={str(r): round(sum(sample['rounds_used'] <= r for sample in resolved) / total, 4)
                  if total else None for r in (1, 5, 10, 20)},
        switches=samples,
    )
