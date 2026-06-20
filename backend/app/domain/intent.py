"""Lightweight intent detection (pure, no framework imports).

Greetings/chit-chat must not go through RAG retrieval — otherwise they hit the
evidence filter and get the "ไม่พบข้อมูล" refusal. We only short-circuit a
message that is a greeting *and nothing else*; "สวัสดีครับ อยากถาม..." still
flows through the normal pipeline.
"""

from __future__ import annotations

import re

GREETING_RESPONSE = (
    "สวัสดีครับ 😊 ผมเป็นผู้ช่วยตอบคำถามเกี่ยวกับการผ่าตัดแบบวันเดียวกลับ (ODS) "
    "ของโรงพยาบาลโพธาราม สอบถามได้เลยครับ เช่น การเตรียมตัวก่อนผ่าตัด "
    "การงดน้ำงดอาหาร หรือการดูแลแผลหลังผ่าตัด"
)

# Polite particles. _GREET_PARTS attaches to the สวัสดี/ว่าไง family (optional);
# _DEE_PARTS is required after a bare "ดี" so plain "ดี"/"ดีนะ" (an
# acknowledgement, not a greeting) does not get captured.
_GREET_PARTS = (
    r"ครับผม|ครับ|คับ|ค้าบ|ค๊าบ|ขอรับ|งับผม|งับ|ง้าบ|ค่ะ|คะ|ขา|"
    r"จ้า|จ้ะ|จ๊ะ|จ๋า|ฮะ|ฮ้า|นะครับ|นะคะ|นะ|เลย"
)
_DEE_PARTS = (
    r"ครับผม|ครับ|คับ|ค้าบ|ค๊าบ|งับผม|งับ|ง้าบ|ค่ะ|คะ|ขา|จ้า|จ้ะ|จ๊ะ|จ๋า|ฮะ|ฮ้า"
)

_THAI_HELLO = (
    r"(?:สวัสดี|สวัสดิ์|อรุณสวัสดิ์|สวัดดี|หวัดดี|วัดดี|"
    r"ฮัลโหล|ฮาโหล|หัลโหล|เฮลโหล|เฮ้)"
    r"(?:ตอน(?:เช้า|สาย|บ่าย|เย็น|ดึก))?"
    rf"(?:{_GREET_PARTS})?"
)
_THAI_DEE = rf"ดี(?:{_DEE_PARTS})"
_THAI_WAI = rf"ว่าไง(?:บ้าง)?(?:{_GREET_PARTS})?"
_EN_HELLO = (
    r"hello+|hi+|hey+|heya|hiya|ya?ho+|yo+|hola|halo+|sup|wa+ssup|"
    r"sawas?dee|sawatdee|good\s?(?:morning|afternoon|evening|day)"
)

_GREETING_RE = re.compile(
    rf"(?:{_THAI_HELLO}|{_THAI_DEE}|{_THAI_WAI}|{_EN_HELLO})", re.IGNORECASE
)

# Collapse runs of 3+ identical chars (เช่น "จ้าาาา" -> "จ้า", "hellooo" -> "hello").
_REPEAT_RE = re.compile(r"(.)\1{2,}")
# Trailing/leading punctuation & common emoji to ignore when matching.
_TRIM_RE = re.compile(r"^[\s]+|[\s!?.,~ๆฯ\U0001F300-\U0001FAFF☀-➿]+$")


def is_greeting(text: str) -> bool:
    """True if the whole message is just a greeting (no real question)."""
    normalized = _REPEAT_RE.sub(r"\1", text.strip().lower())
    normalized = _TRIM_RE.sub("", normalized)
    if not normalized:
        return False
    return _GREETING_RE.fullmatch(normalized) is not None
