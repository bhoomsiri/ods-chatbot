"""BLEU + Thai tokenizer checks (skipped where the libs aren't installed).

These run in the scoring container (sacrebleu + pythainlp present); on a bare host
they skip. BERTScore's sanity lives in the runner (it downloads a 2 GB model).
"""

from __future__ import annotations

import pytest

pytest.importorskip("sacrebleu")
pytest.importorskip("pythainlp")

from eval.metrics.text_metrics import (  # noqa: E402
    corpus_bleu,
    sentence_bleu,
    thai_tokenize,
)


def test_thai_tokenizer_splits_words() -> None:
    seg = thai_tokenize("ผู้ป่วยงดน้ำก่อนผ่าตัด")
    # no spaces in the input, but the segmenter yields several space-joined tokens
    assert " " in seg
    assert len(seg.split()) >= 3
    assert "งด" in seg.split() or "น้ำ" in seg.split()


def test_bleu_identical_is_100() -> None:
    text = "งดน้ำงดอาหารอย่างน้อย 8 ชั่วโมง"
    assert corpus_bleu([text], [text]).bleu == pytest.approx(100.0, abs=1e-6)
    assert sentence_bleu(text, text) == pytest.approx(100.0, abs=1e-6)


def test_bleu_unrelated_is_near_zero() -> None:
    score = corpus_bleu(["แมวสีดำวิ่งไปมาในสวน"], ["งดน้ำงดอาหารก่อนผ่าตัด"]).bleu
    assert 0.0 <= score < 10.0


def test_bleu_precisions_present() -> None:
    res = corpus_bleu(["งดน้ำ 8 ชั่วโมง"], ["งดน้ำ 8 ชั่วโมง"])
    assert len(res.precisions) == 4
    assert all(0.0 <= p <= 100.0 for p in res.precisions)
