"""Independent Claude judge for the KG comparison (fairness gate E).

The answer model is Gemini for BOTH RAGs, so grading with Gemini would be
self-judging. Claude is a third party — it scores each answered item on:
  - correctness: does the answer convey the gold answer's facts? (0..1)
  - faithfulness: is the answer supported by the RAG's own retrieved context,
    with no fabrication? (0..1)
One call per item returns both plus a short Thai rationale. Refusals are scored
by role, not sent to the judge.

Uses ANTHROPIC_API_KEY from the environment (.env). Model pinned for
reproducibility. Same judge + prompt for vector and graphrag → comparable.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass

JUDGE_MODEL = "claude-haiku-4-5-20251001"

_SYSTEM = (
    "คุณเป็นกรรมการประเมินคำตอบของระบบตอบคำถามทางการแพทย์ (One-Day Surgery) "
    "ให้คะแนนอย่างเป็นกลางและเข้มงวด อ้างอิงเฉพาะข้อมูลที่ให้มา ตอบกลับเป็น JSON เท่านั้น"
)

_TEMPLATE = """ประเมินคำตอบของระบบเทียบกับเฉลย

คำถาม:
{question}

เฉลย (gold answer):
{gold}

คำตอบของระบบ:
{answer}

บริบทที่ระบบดึงมาใช้ (retrieved context, อาจถูกตัดให้สั้น):
{context}

ให้คะแนน 2 ด้าน (0.0–1.0):
1. correctness = คำตอบของระบบตรงกับข้อเท็จจริงใน "เฉลย" แค่ไหน (1.0 = ครบถูกต้อง, 0.5 = ถูกบางส่วน/ขาด, 0.0 = ผิดหรือไม่ตอบ)
2. faithfulness = คำตอบมีข้อมูลที่ "บริบทที่ระบบดึงมา" รองรับหรือไม่ ไม่แต่งเติมเกินบริบท (1.0 = ทุกประโยคมีบริบทรองรับ, 0.0 = แต่งขึ้นเอง)

ตอบเป็น JSON เท่านั้น (note ต้องสั้นมาก ไม่เกิน 1 ประโยค):
{{"correctness": <0..1>, "faithfulness": <0..1>, "verdict": "correct|partial|wrong", "note": "<เหตุผลสั้น 1 ประโยค>"}}"""


@dataclass
class JudgeVerdict:
    correctness: float
    faithfulness: float
    verdict: str
    note: str
    error: str | None = None


class ClaudeJudge:
    def __init__(self, *, model: str = JUDGE_MODEL) -> None:
        key = os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            raise RuntimeError("ANTHROPIC_API_KEY required for the Claude judge")
        import anthropic

        self._client = anthropic.Anthropic(api_key=key)
        self._model = model

    def judge(
        self, *, question: str, gold: str, answer: str, context: str
    ) -> JudgeVerdict:
        prompt = _TEMPLATE.format(
            question=question,
            gold=gold or "(ไม่มีเฉลย)",
            answer=answer or "(ระบบไม่ตอบ)",
            context=(context or "(ไม่มีบริบท)")[:6000],
        )
        try:
            msg = self._client.messages.create(
                model=self._model,
                max_tokens=1024,
                temperature=0,
                system=_SYSTEM,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
            if msg.stop_reason == "max_tokens":
                # Truncated JSON → the note ran long. Salvage the numeric scores
                # rather than silently scoring 0 (which corrupts the comparison).
                return _salvage(raw)
            data = json.loads(_extract_json(raw))
            return JudgeVerdict(
                correctness=_clip(data.get("correctness")),
                faithfulness=_clip(data.get("faithfulness")),
                verdict=str(data.get("verdict", "")),
                note=str(data.get("note", ""))[:300],
            )
        except Exception as exc:  # noqa: BLE001 - record, keep the run going
            return JudgeVerdict(0.0, 0.0, "error", "", error=str(exc)[:200])


def _clip(v: object) -> float:
    try:
        return max(0.0, min(1.0, float(v)))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0


def _extract_json(raw: str) -> str:
    raw = raw.replace("```json", "").replace("```", "")
    a, b = raw.find("{"), raw.rfind("}")
    return raw[a : b + 1] if a != -1 and b != -1 else "{}"


def _salvage(raw: str) -> JudgeVerdict:
    """Recover scores from a JSON body truncated mid-note (max_tokens)."""
    import re

    def grab(key: str) -> float | None:
        m = re.search(rf'"{key}"\s*:\s*([0-9]*\.?[0-9]+)', raw)
        return float(m.group(1)) if m else None

    corr, faith = grab("correctness"), grab("faithfulness")
    vm = re.search(r'"verdict"\s*:\s*"([^"]+)"', raw)
    if corr is None and faith is None:
        return JudgeVerdict(0.0, 0.0, "error", "", error="unparseable truncated JSON")
    return JudgeVerdict(
        correctness=_clip(corr),
        faithfulness=_clip(faith if faith is not None else corr),
        verdict=vm.group(1) if vm else "salvaged",
        note="(note truncated; scores salvaged)",
    )
