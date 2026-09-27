"""Hand-computed checks of the deterministic retrieval metrics."""

from __future__ import annotations

import math

import pytest

from eval.metrics.retrieval import (
    hit_at_k,
    mrr,
    ndcg_at_k,
    precision_at_k,
    recall_at_k,
)


def test_hit_at_k_basic() -> None:
    pages = [9, 5, 7]
    gold = {5}
    assert hit_at_k(pages, gold, 1) == 0.0  # page 9 not gold
    assert hit_at_k(pages, gold, 2) == 1.0  # page 5 at rank 2
    assert hit_at_k(pages, gold, 3) == 1.0


def test_recall_at_k_is_distinct_page_level() -> None:
    # Duplicate page 5 must count once; gold has two pages.
    pages = [5, 5, 3]
    gold = {5, 3}
    assert recall_at_k(pages, gold, 1) == pytest.approx(0.5)  # only {5}
    assert recall_at_k(pages, gold, 2) == pytest.approx(0.5)  # still {5}
    assert recall_at_k(pages, gold, 3) == pytest.approx(1.0)  # {5,3}


def test_mrr_first_relevant_rank() -> None:
    assert mrr([9, 5], {5}) == pytest.approx(0.5)  # first hit at rank 2
    assert mrr([5, 3], {5, 3}) == pytest.approx(1.0)  # rank 1
    assert mrr([1, 2], {9}) == 0.0  # never
    assert mrr([9, 5, 3], {3}, k=2) == 0.0  # rank-3 hit excluded by k=2


def test_ndcg_known_values() -> None:
    # [0,1] vs gold {5}: DCG = 1/log2(3); ideal [1,0]: IDCG = 1 -> ndcg = 1/log2(3)
    assert ndcg_at_k([9, 5], {5}, 2) == pytest.approx(1.0 / math.log2(3))
    # perfect ranking -> 1.0
    assert ndcg_at_k([5, 3], {5, 3}, 2) == pytest.approx(1.0)
    # nothing relevant -> 0.0
    assert ndcg_at_k([1, 2], {9}, 2) == 0.0


def test_none_pages_never_relevant() -> None:
    pages = [None, 5]
    gold = {5}
    assert hit_at_k(pages, gold, 1) == 0.0
    assert hit_at_k(pages, gold, 2) == 1.0
    assert mrr(pages, gold) == pytest.approx(0.5)


def test_empty_gold_and_k_guards() -> None:
    assert hit_at_k([1, 2], set(), 3) == 0.0
    assert recall_at_k([1, 2], set(), 3) == 0.0
    assert ndcg_at_k([1, 2], set(), 3) == 0.0
    assert mrr([1, 2], set()) == 0.0
    assert hit_at_k([1], {1}, 0) == 0.0  # k<=0


def test_k_beyond_length() -> None:
    assert hit_at_k([5], {5}, 5) == 1.0
    assert recall_at_k([5], {5}, 5) == pytest.approx(1.0)


def test_precision_at_k_hand_values() -> None:
    # labels [1,0,1] vs gold {5}: precision@2 = 1/2, @3 = 2/3, @1 = 1
    pages = [5, 9, 5]
    gold = {5}
    assert precision_at_k(pages, gold, 2) == pytest.approx(0.5)
    assert precision_at_k(pages, gold, 3) == pytest.approx(2 / 3)
    assert precision_at_k(pages, gold, 1) == pytest.approx(1.0)
    assert precision_at_k(pages, set(), 2) == 0.0
    assert precision_at_k(pages, gold, 0) == 0.0


def test_metrics_are_generic_over_string_keys() -> None:
    # Source-level usage: keys are document names, not page numbers.
    docs = ["LC [แผ่นพับ]", "ริดสีดวง", "hernia"]
    gold = {"hernia", "LC [แผ่นพับ]"}
    assert hit_at_k(docs, gold, 1) == 1.0  # rank-1 doc is gold
    assert recall_at_k(docs, gold, 3) == pytest.approx(1.0)  # both gold docs found
    assert recall_at_k(docs, gold, 1) == pytest.approx(0.5)  # only 1 of 2
    assert mrr(docs, gold) == pytest.approx(1.0)
    assert ndcg_at_k(["x", "hernia"], {"hernia"}, 2) == pytest.approx(1.0 / math.log2(3))
