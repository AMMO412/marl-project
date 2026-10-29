# -*- coding: utf-8 -*-
"""assessment.py —— T-ASL 效果判定接口（可插拔）。

事实模型（《无人集群编队五类任务定义》2.4.2 / T-ASL 实现规范 2026-10-29）：
  * 指令发送、平台到位、动作结束、效果达成是四个不同事实；评估是第五个
    事实：assessment_requested（评估发起）→ assessment_received（评估回传）
    → confirmed（确认）。
  * 评估结果必须绑定 本任务(job_id) + 本对象(target_id) + 当前执行版本(attempt)。
  * 预测与事实分离：本模块不引入概率分配模型；单次结果只由评估接口出。

协议（Adjudicator）：
    adjudicate(task_ref, evidence) -> Adjudication
  task_ref  = {job_id, target_id, attempt, effect_kind, params}
  evidence  = 行为层记录的事实证据（开火日志、覆盖区间、控制区间、
              事件时间线、成员位姿摘要）。
  Adjudication = {items, overall, adjudicator, verified, note}
    items  = [{id, label, required, status, metric, evidence_ref}]
             status ∈ achieved | failed | pending（信息项 status=info）
    overall= succeeded | failed | pending（只对证据可判项汇总）

默认实现 StubAdjudicator：
  按 evidence 的**确定性规则**判定（不掷随机数）；verified=False，
  一切输出标注“桩判定·未验证”。真实外部裁决（仿真裁决 / 战损评估 /
  评估接口）实现同一协议替换即可；HTTP 回调形态本轮只预留不实现。
"""
from typing import Any, Dict, List

# 效果三分类（token → 中文标签）
EFFECT_KINDS = {'damage': '毁伤', 'suppress': '压制', 'seize': '夺占'}
# 中文标签 / 旧字段值 → token
EFFECT_KIND_TOKENS = {
    'damage': 'damage', '毁伤': 'damage',
    'suppress': 'suppress', '压制': 'suppress',
    'seize': 'seize', '夺占': 'seize',
}

STUB_NOTE = '桩判定·未验证：按开火/占位日志的确定性规则演示，未接入真实战损评估或仿真裁决'


def normalize_effect_kind(value, default='damage'):
    """效果类型归一化：接受 token 或中文标签，未知值退回默认。"""
    if value is None:
        return default
    key = str(value).strip()
    return EFFECT_KIND_TOKENS.get(key, EFFECT_KIND_TOKENS.get(key.lower(), default))


def _item(item_id, label, status, required=True, metric=None, evidence_ref=None):
    return dict(id=item_id, label=label, required=required, status=status,
                metric=metric, evidence_ref=evidence_ref)


def _fmt(value):
    return round(float(value), 2) if isinstance(value, (int, float)) else value


class StubAdjudicator:
    """演示桩：从证据出发的确定性判定。

    判定依据与《任务定义》2.4.2 对齐：
      毁伤  按开火日志累计等级，等级 ≥ required_level → 达成；
      压制  按开火日志判覆盖区间，最长连续覆盖 ≥ required_duration → 达成；
      夺占  按占位记录判控制区间，最长连续控制 ≥ required_control_s → 达成；
            移交后坚守为独立结果项，按移交后的保持时长单独结算。
    """

    name = 'constructed_assessment_stub'
    verified = False

    def adjudicate(self, task_ref: Dict[str, Any], evidence: Dict[str, Any]) -> Dict:
        kind = normalize_effect_kind(task_ref.get('effect_kind'))
        params = task_ref.get('params') or {}
        items: List[Dict] = self._effect_item(kind, params, evidence)
        items.extend(self._window_item(evidence))
        if kind == 'seize':
            items.extend(self._hold_items(params, evidence))
        required = [x for x in items if x.get('required')]
        if all(x['status'] == 'achieved' for x in required):
            overall = 'succeeded'
        elif any(x['status'] == 'failed' for x in required):
            overall = 'failed'
        else:
            overall = 'pending'
        return dict(items=items, overall=overall, adjudicator=self.name,
                    verified=self.verified, note=STUB_NOTE,
                    task_ref=dict(task_ref))

    # ---- 各证据项判定 ----
    def _effect_item(self, kind, params, evidence):
        if kind == 'damage':
            level = float(evidence.get('damage_level') or 0.0)
            need = float(params.get('required_level', 3.0))
            return [_item('effect', '毁伤等级不低于规定值',
                          'achieved' if level >= need else 'failed',
                          metric=dict(damage_level=_fmt(level),
                                      required_level=_fmt(need)),
                          evidence_ref='fire_log')]
        if kind == 'suppress':
            longest = float(evidence.get('longest_suppression_s') or 0.0)
            need = float(params.get('required_duration', 10.0))
            return [_item('effect', '目标连续压制不低于规定时长',
                          'achieved' if longest >= need else 'failed',
                          metric=dict(continuous_s=_fmt(longest),
                                      required_duration=_fmt(need)),
                          evidence_ref='coverage_intervals')]
        need = float(params.get('required_control_s', 10.0))
        longest = float(evidence.get('longest_control_s') or 0.0)
        return [_item('effect', '控制权保持不低于规定时长',
                      'achieved' if longest >= need else 'failed',
                      metric=dict(control_s=_fmt(longest),
                                  required_control_s=_fmt(need)),
                      evidence_ref='control_intervals')]

    def _window_item(self, evidence):
        window = evidence.get('window')
        if not window:
            return []
        achieved_t = evidence.get('effect_achieved_t')
        ok = achieved_t is not None and window[0] <= achieved_t <= window[1]
        return [_item('window', '效果在规定时间窗内达成',
                      'achieved' if ok else 'failed',
                      metric=dict(effect_achieved_t=_fmt(achieved_t) if achieved_t is not None else None,
                                  window=[_fmt(v) for v in window]),
                      evidence_ref='timeline')]

    def _hold_items(self, params, evidence):
        need = float(params.get('hold_required_s', 10.0))
        held = float(evidence.get('hold_s') or 0.0)
        handed_over = evidence.get('handover_t') is not None
        ok = handed_over and held >= need
        return [_item('hold_after_handover', '移交后持续坚守',
                      'achieved' if ok else 'failed',
                      metric=dict(hold_s=_fmt(held), required_hold_s=_fmt(need),
                                  handover_t=_fmt(evidence['handover_t'])
                                  if handed_over else None),
                      evidence_ref='control_intervals')]
