"""Text-overlap generation metrics from validated libraries (no hand-rolled math).

- BLEU via ``sacrebleu`` — Thai has no word spaces, so both candidate and
  reference are word-segmented with ``pythainlp`` first and sacreBLEU is run with
  ``tokenize="none"`` (never the default 13a, which would split Thai wrongly).
- BERTScore via ``bert-score`` with a multilingual model (xlm-roberta-large),
  ``rescale_with_baseline=False``, reporting F1. Runs on CPU by default so a
  scoring pass never contends with the live demo's GPU.

Heavy deps are imported lazily; ``pin_versions()`` records exact versions for
provenance. Every score is range-checked (raises on out-of-range → no silent NaN).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass


def pin_versions() -> dict[str, str]:
    """Installed versions of the metric libraries, for the provenance record."""
    import bert_score
    import pythainlp
    import sacrebleu

    return {
        "sacrebleu": sacrebleu.__version__,
        "pythainlp": pythainlp.__version__,
        "bert_score": bert_score.__version__,
    }


def thai_tokenize(text: str) -> str:
    """Word-segment Thai (+ keep latin/number tokens) into a space-joined string
    suitable for sacreBLEU with tokenize='none'."""
    from pythainlp.tokenize import word_tokenize

    tokens = [t for t in word_tokenize(text, engine="newmm") if t.strip()]
    return " ".join(tokens)


_EPS = 1e-6


def _check_pct(value: float, name: str) -> float:
    """Range-check a 0..100 score (D), tolerating float rounding, then clamp."""
    if not -_EPS <= value <= 100.0 + _EPS:
        raise ValueError(f"{name} out of range: {value}")
    return max(0.0, min(100.0, value))


@dataclass(frozen=True)
class BleuResult:
    bleu: float  # corpus BLEU, 0..100
    precisions: list[float]  # BLEU-1..4 n-gram precisions, 0..100


def corpus_bleu(candidates: Sequence[str], references: Sequence[str]) -> BleuResult:
    """Corpus-level BLEU over pre-tokenized Thai. Smoothing handles short answers."""
    import sacrebleu

    if len(candidates) != len(references):
        raise ValueError("candidates/references length mismatch")
    cands = [thai_tokenize(c) for c in candidates]
    refs = [[thai_tokenize(r) for r in references]]
    result = sacrebleu.corpus_bleu(cands, refs, tokenize="none", smooth_method="exp")
    return BleuResult(
        bleu=_check_pct(float(result.score), "BLEU"),
        precisions=[_check_pct(float(p), "BLEU precision") for p in result.precisions],
    )


def sentence_bleu(candidate: str, reference: str) -> float:
    """Sentence-level BLEU (0..100) with exponential smoothing for short text."""
    import sacrebleu

    result = sacrebleu.sentence_bleu(
        thai_tokenize(candidate),
        [thai_tokenize(reference)],
        tokenize="none",
        smooth_method="exp",
    )
    return _check_pct(float(result.score), "sentence BLEU")


def bertscore_f1(
    candidates: Sequence[str],
    references: Sequence[str],
    *,
    model_type: str = "xlm-roberta-large",
    device: str = "cpu",
) -> list[float]:
    """BERTScore F1 per pair (0..1-ish). CPU by default (no GPU contention)."""
    from bert_score import score as bertscore

    if len(candidates) != len(references):
        raise ValueError("candidates/references length mismatch")
    _p, _r, f1 = bertscore(
        list(candidates),
        list(references),
        lang="th",
        model_type=model_type,
        rescale_with_baseline=False,
        device=device,
        verbose=False,
    )
    out: list[float] = []
    for x in f1.tolist():
        v = float(x)
        if not -1.0 - _EPS <= v <= 1.0 + _EPS:
            raise ValueError(f"BERTScore F1 out of range: {v}")
        out.append(max(-1.0, min(1.0, v)))
    return out
