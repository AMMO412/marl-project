# -*- coding: utf-8 -*-
"""
rl/learn_weights.py —— 用进化策略（CEM）学习代价函数权重

为什么先做这个，而不是直接上 MARLlib：
1. 纯标准库，Windows 侧能跑，**今天就能验证"学习确实在优化决策"**
2. 学的是"代价函数权重"，动作空间小（6 维）、结果可解释
3. 学到的权重能和手工三目标权重直接对照，一眼看出学出了什么偏好

方法：CEM（交叉熵方法），无梯度黑箱优化，属强化学习的一支。
它不依赖 ray/gym，所以能在没有 marllib 的环境里先把"学习有效"这件事证明掉，
再拿同样的接口去接 MARLlib（见 train_marllib.py）。

跑法：
    python rl/learn_weights.py
    python rl/learn_weights.py --gens 20 --samples 24 --seeds 0 1 2
"""

import argparse
import contextlib
import io
import os
import random
import statistics
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import contract
import planner
from run_flow import run

NDIM = 8
N_TASKS = 8          # 由 --tasks 覆盖；evaluate() 需要，故设为模块级
FEATURE_NAMES = ["移动时间", "作业时间", "能耗", "拥挤度", "载荷余量",
                 "续航余量", "窗口余量", "紧迫度权重"]

# 第 8 维是特殊的：它不是代价特征，而是**排程阶段的紧迫度权重**
# （planner.URGENCY_WEIGHT）。加它的原因是——短视发生在排程阶段，
# 而排程不看代价函数，所以只学前 7 维**治不了短视**。
# 手工三目标这一维都是 0，正好可以做对照。

# 第 7 维「窗口余量」是本次新增：它把"这个活有多急"送进代价函数，
# 学习才有可能治短视。手工三目标这一维都是 0（不看急不急），
# 所以可以直接对比：学到的权重在第 7 维上是不是非零。


def reward(st):
    """奖励函数（我方暂定，已写入 spec/SPEC.md）。

    这一条决定了"什么叫好的决策"，必须由甲方确认后才算数。
    """
    r = 0.0
    r += 100.0 * st["done"]                  # 完成作业，最主要的收益
    r -= 0.3 * st["used_energy"]             # 能耗代价
    r -= 5.0 * st["conflicts_total"]         # 冲突越少越好
    r -= 50.0 * st["violations"]             # 方案级越界，重罚
    if st["within_rate"] is not None:
        r += 50.0 * st["within_rate"]        # 冲突消解率
    return r


def run_quiet(**kw):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        return run(**kw)


def evaluate(w, seeds, T):
    w = list(w) + [0.0] * (NDIM - len(w))     # 兼容 7 维的手工权重
    planner.COST_WEIGHTS = w[:7]
    planner.URGENCY_WEIGHT = w[7]             # 第 8 维：排程阶段的紧迫度权重
    vals = []
    try:
        for s in seeds:
            _t, _e, st = run_quiet(seed=s, T=T, verbose=False, out_path=None, n_tasks=N_TASKS)
            vals.append(reward(st))
    finally:
        planner.COST_WEIGHTS = None
        planner.URGENCY_WEIGHT = 0.0
    return sum(vals) / len(vals)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--gens", type=int, default=12, help="迭代代数")
    ap.add_argument("--samples", type=int, default=16, help="每代采样数")
    ap.add_argument("--elite", type=int, default=5, help="每代保留的精英数")
    ap.add_argument("--seeds", type=int, nargs="+", default=[0, 1, 2])
    ap.add_argument("--steps", type=int, default=60)
    ap.add_argument("--tasks", type=int, default=8, help="作业数。作业越多，分配决策越关键")
    ap.add_argument("--seed", type=int, default=0, help="学习过程自身的随机种子")
    ap.add_argument("--battery-scale", type=float, default=1.0,
                    help="续航缩放。默认场景下大量作业是「派不出去」而不是「分配不好」，"
                         "放宽续航才能看出分配策略本身的作用")
    ap.add_argument("--window-scale", type=float, default=1.0,
                    help="时间窗缩放。默认场景窗口很松（60~90 步），紧迫度无所谓，"
                         "所以学不出「急的先干」。调紧（如 0.5）才能看出这一维的作用")
    a = ap.parse_args()

    if a.battery_scale != 1.0:
        for k, v in list(contract.PLATFORM_SPECS.items()):
            contract.PLATFORM_SPECS[k] = dict(v, battery=v["battery"] * a.battery_scale)
        print("续航已放宽至 %.1f 倍" % a.battery_scale)

    if a.window_scale != 1.0:
        for k, v in list(contract.TASK_SPECS.items()):
            w0, w1 = v["window"]
            contract.TASK_SPECS[k] = dict(v, window=(w0, w1 * a.window_scale))
        print("时间窗已收紧至 %.1f 倍" % a.window_scale)

    global N_TASKS
    N_TASKS = a.tasks
    rng = random.Random(a.seed)
    mu = [0.5] * NDIM
    sigma = [0.6] * NDIM

    print("进化策略学习代价函数权重")
    print("样本：seed %s，每代 %d 个候选，共 %d 代" % (a.seeds, a.samples, a.gens))
    print("奖励 = 100×完成数 − 0.3×能耗 − 5×冲突 − 50×越界 + 50×消解率")
    print("=" * 78)
    print("%-4s %-12s %-12s %s" % ("代", "最佳奖励", "精英均值", "学到的权重"))
    print("-" * 78)

    best_w, best_r = list(mu), None
    history = []

    for gen in range(a.gens):
        samples = []
        for _ in range(a.samples):
            w = [max(0.0, rng.gauss(mu[j], sigma[j])) for j in range(NDIM)]
            if sum(w) < 1e-6:
                w = [0.1] * NDIM
            samples.append((evaluate(w, a.seeds, a.steps), w))
        samples.sort(key=lambda x: -x[0])

        elite = samples[:a.elite]
        gen_best_r, gen_best_w = elite[0]
        elite_mean = statistics.mean(r for r, _ in elite)
        history.append((gen_best_r, elite_mean))

        if best_r is None or gen_best_r > best_r:
            best_r, best_w = gen_best_r, list(gen_best_w)

        for j in range(NDIM):
            col = [w[j] for _, w in elite]
            mu[j] = statistics.mean(col)
            sigma[j] = (statistics.pstdev(col) if len(col) > 1 else 0.3) + 0.08

        print("%-4d %-12.1f %-12.1f %s"
              % (gen, gen_best_r, elite_mean,
                 " ".join("%.2f" % v for v in gen_best_w)))

    print("-" * 78)
    print("最优奖励 %.1f，权重：%s" % (best_r, " ".join("%.2f" % v for v in best_w)))
    print()

    # ---- 与手工三目标权重对照 ----
    print("对照（同一批 seed、同一个奖励函数）")
    print("=" * 78)
    print("%-14s %-10s %s" % ("权重来源", "奖励", "权重"))
    print("-" * 78)
    for name, w in planner.OBJECTIVE_WEIGHTS.items():
        r = evaluate(w, a.seeds, a.steps)
        print("%-14s %-10.1f %s" % (name, r, " ".join("%.2f" % v for v in w)))
    r_learned = evaluate(best_w, a.seeds, a.steps)
    print("%-14s %-10.1f %s" % ("学习所得", r_learned,
                                " ".join("%.2f" % v for v in best_w)))
    print("-" * 78)

    print("\n学到的偏好（权重越大＝越倾向于避开这类代价）")
    for name, v in zip(FEATURE_NAMES, best_w):
        bar = "#" * int(v * 12)
        print("  %-8s %6.2f  %s" % (name, v, bar))

    gain = r_learned - max(evaluate(w, a.seeds, a.steps)
                           for w in planner.OBJECTIVE_WEIGHTS.values())
    print("\n相对最好的手工目标，提升 %.1f 分（%.1f%%）"
          % (gain, 100 * gain / abs(r_learned) if r_learned else 0))
    print("\n注意：这是在我方暂定奖励函数下的结果。奖励函数本身没经甲方确认，")
    print("      所以「学到了更好的决策」这句话的完整说法是：")
    print("      「在这个奖励定义下，学习找到了比手工权重更好的一组偏好」.")


if __name__ == "__main__":
    main()
