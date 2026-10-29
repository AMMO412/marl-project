# -*- coding: utf-8 -*-
"""
criteria.py —— 完成判定层（新增，对应《五类作战任务_图文版》的要求）

本层回答一个问题：**这个作业到底算不算成功**。

为什么要单独一层：`planning/` 原来只有 `progress >= work` 一条判定，
而《图文版》对判定提出了四条硬性要求，现有实现**一条都不满足**：

  1. 状态要分 7 种，其中**"结果待确认"**是独立状态
     —— 原来只有 open/running/done/failed
  2. 一项判据必须写清**五件事**：对象 / 时间 / 门槛 / 证据 / 缺失处理
     —— 原来只有"工作量"一个数
  3. **全过程要求不能只检查最后一帧**
     —— 原来只看 progress 是否达标，正是"最后一帧"
  4. **完成条件决定"合不合格"，优化指标只用来比"哪种更好"**
     —— 原来两者混在奖励函数里

本层只做判定，不做优化。优劣比较仍在 `planner.COST_TERMS` 与 `rl/`。

> [!warning] 本层是**判据框架**，具体阈值（间隔上限、覆盖门槛、在位台数）仍是【我方暂定】，
> 须由场景配置给出。《图文版》原文即写明："文中的小例子只帮助理解计算和状态，不是项目推荐参数。"
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

# ------------------------------------------------------------------
# 一、任务状态（《图文版》"完成判定的共同规则"表）
#
#   未开始 / 执行中 / 结果待确认 / 成功 / 失败或超时 / 已解除或取消
#
# 失败与超时**分别记录**（原文要求）。过程曾中断、后来恢复时**保留中断记录**——
# 恢复执行能力不会自动抹去之前对严格持续要求的违反。
# ------------------------------------------------------------------
OPEN = "open"                        # 未开始
RUNNING = "running"                  # 执行中
PENDING_CONFIRM = "pending_confirm"  # 结果待确认：动作结束但证据未齐
SUCCESS = "success"                  # 成功
FAILED = "failed"                    # 失败
TIMEOUT = "timeout"                  # 超时
RELEASED = "released"                # 已解除或取消（不自动等同于成功）

TERMINAL = (SUCCESS, FAILED, TIMEOUT, RELEASED)


# ------------------------------------------------------------------
# 二、证据记录
#
# 《图文版》：判据的第四、第五要素是"证据"与"缺失处理"。
# 关键纪律：**记录缺失时先标为待确认，不能把缺记录当作没有违规。**
# 调研文档也反复强调："缺日志不能当作零事件""不能把 0 次事件中的成功率写成 100%"。
# ------------------------------------------------------------------
@dataclass
class Evidence:
    """一条证据。evidence 层负责收集，criteria 层负责采信。"""
    kind: str            # visit / observation / presence / event / result / relay
    at: int              # 时刻（步）
    source: str          # 来源：哪个平台、哪个仿真模块、哪个评估方
    obj: Optional[str] = None    # 对象标识：检查点编号 / 覆盖单元编号 / 信息项 / 目标
    value: Optional[float] = None  # 观测值或状态值（若适用）
    valid: bool = True   # 是否满足"有效"门槛（有效访问要求到达并满足传感条件）
    note: str = ""


# ------------------------------------------------------------------
# 三、判据配置：五要素
# ------------------------------------------------------------------
@dataclass
class Criterion:
    """一项判据必须同时写清五件事。缺任何一件，判定都不可复现。"""
    # ① 对象：分母——待检查的点 / 单元 / 信息项 / 结果项。**评估时不得临时删改。**
    objects: Tuple[str, ...] = ()
    # ① b 必查项：必须逐项满足的子集。**与分母、与总量门槛是三件事**
    #    （《图文版》："总覆盖达标，但一个必查位置遗漏 → 不能判成功"）
    mandatory: Tuple[str, ...] = ()
    # ② 时间
    t_start: int = 0
    t_end: Optional[int] = None
    confirm_deadline: Optional[int] = None   # 结果确认期限（可与执行期限不同）
    # ③ 门槛
    threshold: float = 0.0            # 间隔上限 / 覆盖门槛 / 在位下限 / 状态下限
    # ④ 证据：需要哪些证据种类
    need_kinds: Tuple[str, ...] = ()
    # ⑤ 缺失处理
    on_missing: str = "pending_confirm"      # pending_confirm | fail


@dataclass
class Verdict:
    status: str
    reason: str = ""
    detail: Dict = field(default_factory=dict)

    @property
    def decided(self) -> bool:
        return self.status in TERMINAL


# ------------------------------------------------------------------
# 四、五类判据
#
# 共同纪律：**只检查最后一帧是不合格的。** 下面每个函数都吃"全过程记录"，
# 不是当前值。
# ------------------------------------------------------------------

def _missing(cr: Criterion, got: Sequence[Evidence], what: str) -> Optional[Verdict]:
    """证据不足 → 按缺失处理规则返回待确认或失败。绝不默认合格。"""
    if cr.need_kinds and not any(e.kind in cr.need_kinds and e.valid for e in got):
        if cr.on_missing == "fail":
            return Verdict(FAILED, "缺少%s证据，按规则判失败" % what)
        return Verdict(PENDING_CONFIRM, "缺少%s证据，待确认（不能默认合格）" % what)
    return None


def judge_patrol(cr: Criterion, log: Sequence[Evidence], now: int) -> Verdict:
    """巡逻警戒：最大有效重访间隔（**含开头与结尾的等待**）。

    《图文版》明确：把同一检查点的有效访问时间排序，逐个算相邻间隔，
    再检查开头和结尾的等待，取最长者。**没有有效历史时，应另外规定首次访问期限，
    不能虚构任务开始时已经访问过。**
    """
    m = _missing(cr, log, "有效访问")
    if m:
        return m

    te = cr.t_end if cr.t_end is not None else now
    if now < te:
        pass                      # 未结束也可算，但最终判定要等时段结束
    worst, worst_at = 0.0, None
    for obj in cr.objects:
        ts = sorted(e.at for e in log
                    if e.kind == "visit" and e.valid and e.obj == obj)
        if not ts:
            # 一次都没访问：从头等到现在（或到结束）
            gap = (te if now >= te else now) - cr.t_start
            if gap > worst:
                worst, worst_at = gap, ("%s:从未访问" % obj)
            continue
        head = ts[0] - cr.t_start                      # 开头等待
        tail = (te if now >= te else now) - ts[-1]     # 结尾等待
        gaps = [head, tail] + [b - a for a, b in zip(ts, ts[1:])]
        g = max(gaps)
        if g > worst:
            worst, worst_at = g, ("%s:间隔%.1f" % (obj, g))

    ok = worst <= cr.threshold
    detail = dict(worst_gap=worst, worst_at=worst_at, limit=cr.threshold)
    if now < te:
        return Verdict(RUNNING if ok else FAILED,
                       ("当前最大间隔 %.1f ≤ 上限 %.1f，但时段未结束，不能提前判成功"
                        % (worst, cr.threshold)) if ok
                       else "最大间隔 %.1f 已超上限 %.1f" % (worst, cr.threshold),
                       detail)
    return Verdict(SUCCESS if ok else FAILED,
                   ("最大重访间隔 %.1f ≤ %s" % (worst, cr.threshold)) if ok
                   else "最大重访间隔 %.1f > %s（%s）" % (worst, cr.threshold, worst_at),
                   detail)


def judge_blockade(cr: Criterion, log: Sequence[Evidence], now: int) -> Verdict:
    """区域封控：持续维持 + 禁止事件 + 事件闭合。

    《图文版》三个常见判断错误，本函数逐条防住：
      1. 平台到位 ≠ 控制已建立（只看 presence 不给成功）
      2. 目标被发现 ≠ 通行被阻止（event 需有对应 result 闭环）
      3. 无目标接近 ≠ 有处置能力
    另外：**缺日志 ≠ 零事件**，中间缺一段必须判待确认。
    """
    m = _missing(cr, log, "控制状态")
    if m:
        return m

    te = cr.t_end if cr.t_end is not None else now
    ctrl = [e for e in log if e.kind == "presence"]
    spans = sorted((e.at, e.value) for e in ctrl if e.value is not None)
    # 记录覆盖是否连续：缺一段就 pending
    covered = set(e.at for e in ctrl)
    if spans:
        gap = [t for t in range(cr.t_start, min(now, te) + 1) if t not in covered]
        if gap:
            return Verdict(PENDING_CONFIRM,
                           "控制状态记录缺失 %d 个时刻，无法区分'没中断'与'没记录'" % len(gap),
                           dict(missing_steps=gap[:10]))

    violated = [e for e in log if e.kind == "event" and e.valid and not e.note]
    # 禁止事件：value 为 1 表示发生该规则禁止的通行事件
    bad = [e for e in log if e.kind == "event" and e.value]
    if bad:
        return Verdict(FAILED, "发生 %d 次规则禁止的通行事件" % len(bad),
                       dict(at=[e.at for e in bad]))

    # 事件闭合：要求处理的事件必须有对应结果反馈，未收到反馈不算成功
    need_result = [e for e in log if e.kind == "event"]
    got_result = set(e.obj for e in log if e.kind == "result" and e.valid)
    unclosed = [e for e in need_result if e.obj not in got_result]
    if unclosed:
        return Verdict(PENDING_CONFIRM,
                       "%d 个事件未收到处置结果反馈，不算成功" % len(unclosed),
                       dict(unclosed=[e.obj for e in unclosed]))

    if now < te:
        return Verdict(RUNNING, "维持中（%d→%d）" % (cr.t_start, te))
    return Verdict(SUCCESS, "控制时段内无禁止事件且事件均已闭合", dict(n_event=len(need_result)))


def judge_recon(cr: Criterion, log: Sequence[Evidence], now: int) -> Verdict:
    """协同侦察：合并有效覆盖（**并集，不是相加**）+ 回传确认。

    《图文版》：合并覆盖率 = 至少被一次有效观测的单元数 ÷ 要求覆盖单元总数。
    各平台取并集，**重叠只算一次**。总量达标不能替代必查项。
    另外：必要复核带来的重叠**不是自动扣分**——判据层不做去重惩罚，
    那是优化指标的事（`planner` 的代价函数），两者不许混。
    """
    m = _missing(cr, log, "有效观测")
    if m:
        return m

    seen = {e.obj for e in log
            if e.kind == "observation" and e.valid and e.obj is not None}
    total = len(cr.objects)                       # 分母固定，不得评估时删改
    union = len(seen & set(cr.objects)) if cr.objects else len(seen)
    # 必查项逐项核对：总量门槛不能替代必查项
    missing_obj = [o for o in cr.mandatory if o not in seen]
    ratio = (union / total) if total else 0.0
    detail = dict(union=union, total=total, ratio=round(ratio, 3),
                  missing=missing_obj[:10])
    if missing_obj:
        return Verdict(FAILED, "有 %d 个必查单元未覆盖，总量门槛不能替代必查项" % len(missing_obj),
                       detail)
    if union < cr.threshold:
        return Verdict(FAILED, "合并覆盖 %d < 门槛 %s" % (union, cr.threshold), detail)
    if now < (cr.t_end if cr.t_end is not None else now):
        return Verdict(RUNNING, "覆盖达标但时段未结束", detail)
    relayed = any(e.kind == "relay" and e.valid for e in log)
    if not relayed:
        return Verdict(PENDING_CONFIRM, "覆盖达标，但回传未确认", detail)
    return Verdict(SUCCESS, "合并覆盖 %d/%d 且回传已确认" % (union, total), detail)


def judge_assault(cr: Criterion, log: Sequence[Evidence], now: int) -> Verdict:
    """机动突击：**结果必须由约定评估反馈确认**，预测概率不能替代。

    《图文版》明确："分配论文可以使用预期结果的概率来比较方案，但预测概率和
    已经发生的结果不是同一件事。" 所以本函数**不计算概率**，
    只检查：执行有记录 → 结果有确认 → 关联正确 → 期限合格。
    """
    m = _missing(cr, log, "执行")
    if m:
        return m

    executed = [e for e in log if e.kind == "event" and e.valid]
    if not executed:
        return Verdict(RUNNING, "尚无有效执行记录（指令已发送不算已执行）")

    results = [e for e in log if e.kind == "result"]
    if not any(e.valid for e in results):
        if cr.confirm_deadline is not None and now > cr.confirm_deadline:
            return Verdict(TIMEOUT, "到确认期限仍无有效结果")
        return Verdict(PENDING_CONFIRM, "动作结束但结果未确认（不能因动作结束直接判成功）")

    # 关联正确：结果必须对应本任务对象
    ok_obj = [e for e in results if e.valid and (not cr.objects or e.obj in cr.objects)]
    if len(ok_obj) < len(cr.objects or []):
        return Verdict(FAILED, "结果项不全：%d/%d" % (len(ok_obj), len(cr.objects or [])),
                       dict(got=[e.obj for e in ok_obj]))
    return Verdict(SUCCESS, "结果已由评估方确认且关联正确", dict(n_result=len(ok_obj)))


def judge_hold(cr: Criterion, log: Sequence[Evidence], now: int) -> Verdict:
    """要点坚守：全时段持续满足在位（或状态）下限，**含接替时刻**。

    《图文版》两个要点：
      - **最后一帧和平均值不能代替全过程**
      - 轮换要记录谁离开、谁接替；**不能仅凭安排表计划有人就认定已接替**
    判据可选"有效在位数量"或"守护状态下限"，但**不能未经说明就互相替代**。
    """
    m = _missing(cr, log, "在位")
    if m:
        return m

    te = cr.t_end if cr.t_end is not None else now
    end = min(now, te)
    worst_t, worst_n = None, None
    for t in range(cr.t_start, end + 1):
        # 该时刻的**有效在位台数**：按"来源（平台）"去重，不是累计条数。
        # presence(value>0) 表示这台此刻在位；value=0 或 invalid 表示离位/失效。
        present = {e.source for e in log
                   if e.kind == "presence" and e.at == t and e.valid
                   and (e.value or 0.0) > 0}
        n = len(present)
        if worst_n is None or n < worst_n:
            worst_n, worst_t = n, t
    detail = dict(min_present=worst_n, at=worst_t, required=cr.threshold,
                  span=(cr.t_start, end))
    if worst_n is None:
        return Verdict(PENDING_CONFIRM, "无在位记录（没有记录不算有人在位）", detail)
    if worst_n < cr.threshold:
        return Verdict(FAILED, "第 %s 时刻在位 %s < 要求 %s（全过程下限，最后一帧不能代替）"
                       % (worst_t, worst_n, cr.threshold), detail)
    if now < te:
        return Verdict(RUNNING, "维持中，当前最低在位 %s" % worst_n, detail)
    return Verdict(SUCCESS, "全时段在位不低于 %s（最低 %s）" % (cr.threshold, worst_n), detail)


# ------------------------------------------------------------------
# 五、分派
# ------------------------------------------------------------------
JUDGES = {
    "patrol": judge_patrol,
    "blockade": judge_blockade,
    "recon": judge_recon,
    "assault": judge_assault,
    "hold": judge_hold,
}


def judge(ttype: str, cr: Criterion, log: Sequence[Evidence], now: int) -> Verdict:
    fn = JUDGES.get(ttype)
    if fn is None:
        return Verdict(FAILED, "未知任务类型 %r" % ttype)
    return fn(cr, log, now)


# ------------------------------------------------------------------
# 自测：用例全部取自《五类作战任务_图文版》的示例
# ------------------------------------------------------------------
if __name__ == "__main__":
    def v(*evs):
        return list(evs)

    # 巡逻：时段 0–30，上限 10，开始时有第 0 分钟的有效访问
    cr = Criterion(objects=("A",), t_start=0, t_end=30, threshold=10,
                   need_kinds=("visit",))
    ok = [Evidence("visit", 0, "P1", "A"), Evidence("visit", 8, "P1", "A"),
          Evidence("visit", 17, "P1", "A"), Evidence("visit", 26, "P1", "A")]
    bad = [Evidence("visit", 0, "P1", "A"), Evidence("visit", 8, "P1", "A"),
           Evidence("visit", 22, "P1", "A"), Evidence("visit", 29, "P1", "A")]
    print("巡逻 0/8/17/26 :", judge("patrol", cr, ok, 30).status,
          judge("patrol", cr, ok, 30).reason)
    print("巡逻 0/8/22/29 :", judge("patrol", cr, bad, 30).status,
          judge("patrol", cr, bad, 30).reason)
    print("巡逻 中途(20)  :", judge("patrol", cr, ok, 20).status)
    print("巡逻 无任何记录:", judge("patrol", cr, [], 30).status,
          judge("patrol", cr, [], 30).reason)

    # 侦察：100 单元，门槛 90；甲 60 乙 50 重叠 20 → 并集 90
    objs = tuple("u%d" % i for i in range(100))
    cr2 = Criterion(objects=objs, t_start=0, t_end=50, threshold=90,
                    need_kinds=("observation",))
    evs = [Evidence("observation", 5, "A", "u%d" % i) for i in range(60)]
    evs += [Evidence("observation", 6, "B", "u%d" % i) for i in range(40, 90)]
    r = judge("recon", cr2, evs, 50)
    print("侦察 并集90    :", r.status, r.reason, r.detail)
    print("侦察 +回传     :", judge("recon", cr2, evs + [Evidence("relay", 48, "rx")], 50).status)
    cr2b = Criterion(objects=objs, mandatory=("u95",), t_start=0, t_end=50,
                     threshold=90, need_kinds=("observation",))
    evs2 = evs + [Evidence("observation", 9, "C", "u95")]
    print("侦察 缺必查u95 :", judge("recon", cr2b, evs, 50).status)
    print("侦察 补上u95   :", judge("recon", cr2b, evs2 + [Evidence("relay", 48, "rx")], 50).status)

    # 坚守：0–20 始终 ≥2；甲全程、乙到 10 离开、丙第 9 到位
    cr3 = Criterion(objects=("K",), t_start=0, t_end=20, threshold=2,
                    need_kinds=("presence",))
    base = [Evidence("presence", 0, "甲", "K", 1.0),
            Evidence("presence", 0, "乙", "K", 1.0),
            Evidence("presence", 10, "乙", "K", -1.0)]
    print("坚守 丙第9到位 :", judge("hold", cr3, base + [Evidence("presence", 9, "丙", "K", 1.0)], 20).status)
    print("坚守 丙第11到位:", judge("hold", cr3, base + [Evidence("presence", 11, "丙", "K", 1.0)], 20).status,
          judge("hold", cr3, base + [Evidence("presence", 11, "丙", "K", 1.0)], 20).reason)

    # 封控：0 次事件不能写成 100%，缺日志必须待确认
    cr4 = Criterion(objects=(), t_start=0, t_end=20, threshold=0, need_kinds=("presence",))
    full = [Evidence("presence", t, "gate", None, 1.0) for t in range(0, 21)]
    holed = [e for e in full if e.at != 7]
    print("封控 记录完整  :", judge("blockade", cr4, full, 20).status)
    print("封控 缺第7时刻 :", judge("blockade", cr4, holed, 20).status,
          judge("blockade", cr4, holed, 20).reason)
    print("封控 有禁止事件:", judge("blockade", cr4,
          full + [Evidence("event", 5, "gate", "E1", 1.0)], 20).status)

    # 突击：动作结束但结果未回 → 待确认；超确认期限 → 超时
    cr5 = Criterion(objects=("T1",), t_start=0, t_end=30, confirm_deadline=35,
                    need_kinds=("event",))
    ex = [Evidence("event", 10, "P1", "T1", 1.0)]
    print("突击 执行未确认:", judge("assault", cr5, ex, 12).status)
    print("突击 超确认期  :", judge("assault", cr5, ex, 36).status)
    print("突击 结果确认  :", judge("assault", cr5, ex + [Evidence("result", 12, "eval", "T1", 1.0)], 12).status)
