"""Pearson + Spearman correlation checks (hand-computable)."""

from __future__ import annotations

import pytest

from eval.metrics.correlation import pearson, spearman


def test_pearson_perfect_positive() -> None:
    assert pearson([1, 2, 3], [2, 4, 6]) == pytest.approx(1.0)


def test_pearson_perfect_negative() -> None:
    assert pearson([1, 2, 3], [6, 4, 2]) == pytest.approx(-1.0)


def test_pearson_degenerate_returns_zero() -> None:
    assert pearson([1, 1, 1], [1, 2, 3]) == 0.0  # zero variance in x
    assert pearson([5.0], [5.0]) == 0.0  # n < 2


def test_spearman_monotonic_nonlinear_is_one() -> None:
    # y = x^3 is monotonic -> Spearman 1.0 even though Pearson < 1
    xs = [1.0, 2.0, 3.0, 4.0]
    ys = [1.0, 8.0, 27.0, 64.0]
    assert spearman(xs, ys) == pytest.approx(1.0)
    assert pearson(xs, ys) < 1.0


def test_spearman_handles_ties() -> None:
    # tied ranks shouldn't blow up; identical series -> 1.0
    assert spearman([1.0, 1.0, 2.0], [3.0, 3.0, 9.0]) == pytest.approx(1.0)
