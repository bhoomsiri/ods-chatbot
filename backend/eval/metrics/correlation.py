"""Pearson + Spearman correlation (pure Python, no scipy).

Used for comparison #4 — how well the new Claude judge agrees with the original
Gemini-Flash judge, per question. Both return 0.0 for a degenerate input (fewer
than two points, or a constant series with no variance) rather than NaN.
"""

from __future__ import annotations

import math
from collections.abc import Sequence


def pearson(xs: Sequence[float], ys: Sequence[float]) -> float:
    if len(xs) != len(ys):
        raise ValueError("length mismatch")
    n = len(xs)
    if n < 2:
        return 0.0
    mx = sum(xs) / n
    my = sum(ys) / n
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=True))
    vx = sum((x - mx) ** 2 for x in xs)
    vy = sum((y - my) ** 2 for y in ys)
    if vx == 0.0 or vy == 0.0:
        return 0.0
    return cov / math.sqrt(vx * vy)


def _rank(values: Sequence[float]) -> list[float]:
    """Average ranks (1-indexed); tied values share the mean of their ranks."""
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        avg = (i + j) / 2.0 + 1.0  # mean of ranks i..j, 1-indexed
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    return ranks


def spearman(xs: Sequence[float], ys: Sequence[float]) -> float:
    if len(xs) != len(ys):
        raise ValueError("length mismatch")
    if len(xs) < 2:
        return 0.0
    return pearson(_rank(xs), _rank(ys))
