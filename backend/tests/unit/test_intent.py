from __future__ import annotations

import pytest

from app.domain.intent import is_greeting


@pytest.mark.parametrize(
    "text",
    [
        "สวัสดี",
        "สวัสดีครับ",
        "สวัสดีค่ะ",
        "หวัดดีครับ",
        "สวัสดีตอนเช้า",
        "สวัสดีจ้า",
        "ดีจ้า",
        "ดีครับ",
        "ดีค่ะ",
        "ดีงับ",
        "ดีงับผม",
        "สวัสดีงับ",
        "ดีจ้าาาา",  # elongation
        "หวัดดีจ้า",
        "ว่าไงครับ",
        "ฮัลโหล",
        "เฮ้",
        "  สวัสดีครับ!! ",
        "สวัสดีครับ 👋",
        "hello",
        "Hi",
        "hey",
        "helloooo",
        "good morning",
    ],
)
def test_detects_pure_greetings(text: str) -> None:
    assert is_greeting(text)


@pytest.mark.parametrize(
    "text",
    [
        "สวัสดีครับ อยากสอบถามเรื่องการผ่าตัด",  # greeting + real question
        "ก่อนผ่าตัดงดน้ำงดอาหารกี่ชั่วโมง",
        "การดูแลแผลหลังผ่าตัด",
        "ดูแลแผลยังไงดีครับ",
        "",
        "ขอบคุณสำหรับข้อมูลเรื่องการผ่าตัด",
        "ดี",  # bare "ดี" is ambiguous, not a greeting
        "ดีมาก",
    ],
)
def test_ignores_non_greetings(text: str) -> None:
    assert not is_greeting(text)
