"""LLM-judge helpers: parsing, fake judge, deterministic aggregation."""

from __future__ import annotations

import math

import pytest

from eval.metrics.llm_judge import (
    FakeJudge,
    bootstrap_ci,
    mean_sd,
    parse_score,
)


def test_parse_score_extracts_and_clamps() -> None:
    assert parse_score("0.8") == pytest.approx(0.8)
    assert parse_score("คะแนน: 0.75") == pytest.approx(0.75)
    assert parse_score("1.5") == 1.0  # clamp high
    assert parse_score("-0.2") == 0.0  # clamp low
    with pytest.raises(ValueError):
        parse_score("ไม่มีตัวเลข")


def test_mean_sd() -> None:
    assert mean_sd([]) == (0.0, 0.0)
    assert mean_sd([0.7]) == (0.7, 0.0)
    mean, sd = mean_sd([0.0, 1.0])
    assert mean == pytest.approx(0.5)
    assert sd == pytest.approx(math.sqrt(0.5))  # sample stdev of {0,1}


def test_bootstrap_ci_is_deterministic_and_bracketed() -> None:
    vals = [0.2, 0.4, 0.6, 0.8, 1.0]
    lo1, hi1 = bootstrap_ci(vals, seed=42)
    lo2, hi2 = bootstrap_ci(vals, seed=42)
    assert (lo1, hi1) == (lo2, hi2)  # reproducible
    assert lo1 <= 0.6 <= hi1  # brackets the mean
    # constant sample -> degenerate CI
    assert bootstrap_ci([0.5, 0.5, 0.5]) == (0.5, 0.5)
    assert bootstrap_ci([0.9]) == (0.9, 0.9)
    assert bootstrap_ci([]) == (0.0, 0.0)


@pytest.mark.asyncio
async def test_fake_judge_overlap_scores() -> None:
    judge = FakeJudge()
    # every answer word appears in context -> faithfulness 1.0
    f = await judge.faithfulness(answer="งด น้ำ", contexts=["ผู้ป่วย งด น้ำ ก่อน ผ่าตัด"])
    assert f == pytest.approx(1.0)
    # half the answer words appear in the question
    r = await judge.answer_relevancy(question="งด อาหาร", answer="งด เหล้า")
    assert r == pytest.approx(0.5)
