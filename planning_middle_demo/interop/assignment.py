# -*- coding: utf-8 -*-
"""匈牙利一对一分配（JV 实现，移植自 M2 的纯标准库版本）。

用于协同组内“槽位 × 平台”的最优匹配；平台数可以多于槽位数，
保证每个槽位至多一台平台、每台平台至多一个槽位。
"""

from typing import List, Sequence, Tuple


def hungarian(cost: Sequence[Sequence[float]]) -> List[Tuple[int, int]]:
    """返回 [(row, col), ...]；不可行单元用大数填充。"""
    n = len(cost)
    m = len(cost[0]) if n else 0
    if n == 0 or m == 0:
        return []

    transposed = False
    matrix = [list(row) for row in cost]
    if n > m:
        matrix = [[matrix[i][j] for i in range(n)] for j in range(m)]
        n, m = m, n
        transposed = True

    INF = float("inf")
    u = [0.0] * (n + 1)
    v = [0.0] * (m + 1)
    p = [0] * (m + 1)
    way = [0] * (m + 1)

    for i in range(1, n + 1):
        p[0] = i
        j0 = 0
        minv = [INF] * (m + 1)
        used = [False] * (m + 1)
        while True:
            used[j0] = True
            i0 = p[j0]
            delta = INF
            j1 = -1
            row = matrix[i0 - 1]
            for j in range(1, m + 1):
                if used[j]:
                    continue
                cur = row[j - 1] - u[i0] - v[j]
                if cur < minv[j]:
                    minv[j] = cur
                    way[j] = j0
                if minv[j] < delta:
                    delta = minv[j]
                    j1 = j
            if j1 < 0:
                break
            for j in range(m + 1):
                if used[j]:
                    u[p[j]] += delta
                    v[j] -= delta
                else:
                    minv[j] -= delta
            j0 = j1
            if p[j0] == 0:
                break
        while j0:
            j1 = way[j0]
            p[j0] = p[j1]
            j0 = j1

    result = []
    for j in range(1, m + 1):
        if p[j]:
            i, col = p[j] - 1, j - 1
            result.append((col, i) if transposed else (i, col))
    return result
