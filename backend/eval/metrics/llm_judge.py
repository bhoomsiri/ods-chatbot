"""LLM-as-judge generation metrics (faithfulness, answer relevancy).

A transparent, self-contained alternative to the RAGAS library: the same two
core signals, computed by our own Gemini judge behind a ``Judge`` port so it is
swappable (RAGAS proper can be dropped in later) and unit-testable with a fake.

- faithfulness     : fraction of the answer's claims supported by the contexts
                     (groundedness — the §5 "answer only from the manual" rule).
- answer_relevancy : how directly the answer addresses the question.

Both in [0, 1], judged at temperature 0. Aggregation helpers report mean ± sd and
a seeded (reproducible) bootstrap 95% CI, per the harness's statistical rigor.
"""

from __future__ import annotations

import random
import re
import statistics
from collections.abc import Sequence
from typing import Protocol, runtime_checkable


@runtime_checkable
class Judge(Protocol):
    async def faithfulness(self, *, answer: str, contexts: Sequence[str]) -> float: ...

    async def answer_relevancy(self, *, question: str, answer: str) -> float: ...


_FLOAT_RE = re.compile(r"[-+]?\d*\.?\d+")


def parse_score(text: str) -> float:
    """Extract the first number from a judge reply and clamp to [0, 1]."""
    m = _FLOAT_RE.search(text)
    if m is None:
        raise ValueError(f"no numeric score in judge reply: {text!r}")
    return max(0.0, min(1.0, float(m.group())))


def mean_sd(values: Sequence[float]) -> tuple[float, float]:
    """(mean, sample sd). sd is 0.0 for fewer than two values."""
    if not values:
        return (0.0, 0.0)
    mean = statistics.fmean(values)
    sd = statistics.stdev(values) if len(values) > 1 else 0.0
    return (mean, sd)


def bootstrap_ci(
    values: Sequence[float],
    *,
    confidence: float = 0.95,
    n_resamples: int = 1000,
    seed: int = 0,
) -> tuple[float, float]:
    """Percentile bootstrap CI of the mean. Deterministic given ``seed``."""
    if not values:
        return (0.0, 0.0)
    if len(values) == 1:
        return (values[0], values[0])
    rng = random.Random(seed)
    n = len(values)
    means: list[float] = []
    for _ in range(n_resamples):
        sample = [values[rng.randrange(n)] for _ in range(n)]
        means.append(statistics.fmean(sample))
    means.sort()
    lo_idx = int((1.0 - confidence) / 2.0 * n_resamples)
    hi_idx = int((1.0 + confidence) / 2.0 * n_resamples) - 1
    return (means[lo_idx], means[hi_idx])


class FakeJudge:
    """Deterministic judge for unit tests + fake mode (no network).

    Scores are a stable function of the inputs so tests can assert exact values:
    faithfulness rewards answers whose words appear in the contexts; relevancy
    rewards answers that share words with the question.
    """

    @staticmethod
    def _overlap(a: str, b: str) -> float:
        wa = set(a.split())
        wb = set(b.split())
        if not wa:
            return 0.0
        return len(wa & wb) / len(wa)

    async def faithfulness(self, *, answer: str, contexts: Sequence[str]) -> float:
        return self._overlap(answer, " ".join(contexts))

    async def answer_relevancy(self, *, question: str, answer: str) -> float:
        return self._overlap(answer, question)


_FAITHFULNESS_PROMPT = (
    "คุณเป็นผู้ตรวจสอบความถูกต้องของคำตอบทางการแพทย์ "
    "ประเมินว่า 'คำตอบ' อ้างอิงได้จาก 'บริบท' ที่ให้มาเพียงใด "
    "ให้คะแนนเป็นสัดส่วนของข้อความในคำตอบที่มีหลักฐานรองรับในบริบท "
    "ตอบกลับเป็นตัวเลขทศนิยมเดียวระหว่าง 0.0 ถึง 1.0 เท่านั้น ห้ามมีข้อความอื่น\n\n"
    "บริบท:\n{contexts}\n\nคำตอบ:\n{answer}\n\nคะแนน:"
)
_RELEVANCY_PROMPT = (
    "ประเมินว่า 'คำตอบ' ตรงประเด็นและตอบ 'คำถาม' โดยตรงเพียงใด "
    "ตอบกลับเป็นตัวเลขทศนิยมเดียวระหว่าง 0.0 ถึง 1.0 เท่านั้น ห้ามมีข้อความอื่น\n\n"
    "คำถาม:\n{question}\n\nคำตอบ:\n{answer}\n\nคะแนน:"
)


class GeminiJudge:
    """Gemini-backed judge. Lazy-imports google.generativeai (real runs only)."""

    def __init__(self, *, api_key: str, model: str = "gemini-2.5-flash") -> None:
        self._api_key = api_key
        self._model_name = model

    def _generate(self, prompt: str) -> str:
        import google.generativeai as genai

        genai.configure(api_key=self._api_key)
        model = genai.GenerativeModel(self._model_name)
        # gemini-2.5-flash is a thinking model: a tiny max_output_tokens gets
        # consumed by reasoning, leaving no answer Part (finish_reason=MAX_TOKENS)
        # and making resp.text raise. Give it room, and extract text defensively.
        resp = model.generate_content(
            prompt, generation_config={"temperature": 0.0, "max_output_tokens": 2048}
        )
        try:
            return str(resp.text)
        except Exception:
            for cand in getattr(resp, "candidates", None) or []:
                content = getattr(cand, "content", None)
                parts = getattr(content, "parts", None) or []
                text = "".join(getattr(p, "text", "") or "" for p in parts)
                if text.strip():
                    return text
            raise ValueError("judge returned no text part") from None

    async def faithfulness(self, *, answer: str, contexts: Sequence[str]) -> float:
        prompt = _FAITHFULNESS_PROMPT.format(
            contexts="\n---\n".join(contexts), answer=answer
        )
        return parse_score(self._generate(prompt))

    async def answer_relevancy(self, *, question: str, answer: str) -> float:
        prompt = _RELEVANCY_PROMPT.format(question=question, answer=answer)
        return parse_score(self._generate(prompt))
