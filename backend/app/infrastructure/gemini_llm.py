"""Gemini adapters: query reformulation (Flash-Lite) + answer streaming (2.5 Pro).

Lazily imports google.generativeai. Enforces the safety system prompt (§5) and
low temperature for safety-critical answers.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator, Sequence
from typing import Any

from app.domain.entities import ChatTurn, ChunkTag, QueryAnalysis, ScoredChunk
from app.domain.errors import QuotaExceededError


def _is_quota_error(exc: Exception) -> bool:
    """True if the exception is a Gemini quota / rate-limit (429) error."""
    text = f"{type(exc).__name__} {exc}".lower()
    return (
        type(exc).__name__ == "ResourceExhausted"
        or "429" in text
        or "resource_exhausted" in text
        or "quota" in text
        or "rate limit" in text
    )


_ANSWER_SYSTEM_PROMPT = """คุณคือผู้ช่วยให้ข้อมูลเรื่องการผ่าตัดแบบวันเดียว (One-Day Surgery)
ของโรงพยาบาลโพธาราม ปฏิบัติตามกฎต่อไปนี้อย่างเคร่งครัด:
1. ตอบโดยใช้ข้อมูลจาก "เอกสารอ้างอิง" ที่ให้มาเท่านั้น ห้ามแต่งเติมข้อมูลนอกเหนือจากนี้
2. ห้ามใส่ชื่อแหล่งที่มาหรือเลขหน้าในเนื้อคำตอบ (ห้ามเขียนวงเล็บอ้างอิง เช่น
   "(ODS MIS 2565 หน้า 12)") เพราะระบบแสดงแหล่งอ้างอิงแยกให้ผู้ใช้แล้ว
   ให้ตอบเป็นเนื้อหาล้วน ๆ
3. ห้ามวินิจฉัยโรคหรือสั่งจ่ายยา หากผู้ใช้ถามเชิงวินิจฉัย ให้แนะนำให้ปรึกษาเจ้าหน้าที่
4. เน้นย้ำคำสั่งที่สำคัญต่อความปลอดภัยก่อนเสมอ ได้แก่ การงดน้ำงดอาหาร (NPO)
   และการดูแลแผล (แผลห้ามโดนน้ำ)
5. ตอบเป็นภาษาไทย กระชับ ชัดเจน ใช้ Markdown (ตัวหนา/หัวข้อย่อย) ได้เพื่อให้อ่านง่าย
   ห้ามแยกหรือระบุว่าข้อมูลส่วนใดเป็น "ข้อมูลทั่วไป" หรือ "ข้อมูลเฉพาะของโรงพยาบาล"
   ให้เรียบเรียงเป็นคำตอบเดียวที่ต่อเนื่อง"""


def _format_context(contexts: Sequence[ScoredChunk]) -> str:
    blocks = []
    for c in contexts:
        ref = f"{c.chunk.source} หน้า {c.chunk.page}"
        blocks.append(f"[{ref}]\n{c.chunk.text}")
    return "\n\n".join(blocks)


class GeminiAnswerLLM:
    def __init__(
        self, *, api_key: str, model: str = "gemini-2.5-pro", temperature: float = 0.1
    ) -> None:
        self._api_key = api_key
        self._model_name = model
        self._temperature = temperature
        self._model: Any | None = None

    def _ensure_model(self) -> Any:
        if self._model is None:
            import google.generativeai as genai

            genai.configure(api_key=self._api_key)
            self._model = genai.GenerativeModel(
                self._model_name, system_instruction=_ANSWER_SYSTEM_PROMPT
            )
        return self._model

    async def stream(
        self,
        *,
        question: str,
        contexts: Sequence[ScoredChunk],
        history: Sequence[ChatTurn] = (),
    ) -> AsyncIterator[str]:
        import google.generativeai as genai

        model = self._ensure_model()
        convo = "\n".join(f"{t.role}: {t.content}" for t in history[-6:])
        history_block = f"บทสนทนาก่อนหน้า (ใช้เข้าใจคำถามต่อเนื่องเท่านั้น):\n{convo}\n\n" if convo else ""
        prompt = (
            f"เอกสารอ้างอิง:\n{_format_context(contexts)}\n\n"
            f"{history_block}"
            f"คำถามล่าสุด: {question}\n\nคำตอบ:"
        )
        config = genai.types.GenerationConfig(temperature=self._temperature)

        # The SDK is synchronous; iterate its stream in a worker thread and
        # hand chunks back to the event loop via a queue.
        queue: asyncio.Queue[str | None] = asyncio.Queue()
        loop = asyncio.get_running_loop()

        def _produce() -> None:
            try:
                for chunk in model.generate_content(
                    prompt, generation_config=config, stream=True
                ):
                    text = getattr(chunk, "text", "")
                    if text:
                        loop.call_soon_threadsafe(queue.put_nowait, text)
            finally:
                loop.call_soon_threadsafe(queue.put_nowait, None)

        task = loop.run_in_executor(None, _produce)
        try:
            while True:
                item = await queue.get()
                if item is None:
                    break
                yield item
            await task  # surface any exception raised inside the worker thread
        except Exception as exc:
            if _is_quota_error(exc):
                raise QuotaExceededError(str(exc)) from exc
            raise


_ANALYZE_PROMPT = """คุณคือตัวช่วยวิเคราะห์คำถามก่อนค้นเอกสาร สำหรับระบบให้ข้อมูล
การผ่าตัดแบบวันเดียวกลับ (One-Day Surgery, ODS) ของโรงพยาบาลโพธาราม
วิเคราะห์ "คำถามล่าสุด" โดยอ้างอิงบทสนทนาก่อนหน้า แล้วตอบกลับเป็น JSON เท่านั้น
ตามรูปแบบนี้:
{
  "in_scope": true/false,
  "reformulated": "คำถามที่เขียนใหม่ให้สมบูรณ์ในตัวเอง (standalone)",
  "sub_queries": ["ประเด็นย่อยที่ 1", "ประเด็นย่อยที่ 2"],
  "reason": "เหตุผลสั้น ๆ"
}

กฎ:
- in_scope = false เฉพาะเมื่อคำถาม "ไม่เกี่ยวข้องอย่างชัดเจน" กับการผ่าตัด สุขภาพ
  หรือบริการของโรงพยาบาล (เช่น ถามเรื่องดินฟ้าอากาศ การเมือง กีฬา เขียนโปรแกรม)
  หากไม่แน่ใจ หรือพอจะเกี่ยวกับการแพทย์/การผ่าตัด/โรงพยาบาล ให้ in_scope = true เสมอ
- reformulated: แก้คำสรรพนาม/บริบทให้ครบ เป็นประโยคค้นหาเดียวที่สมบูรณ์ และใช้ถ้อยคำ
  แบบที่น่าจะปรากฏในเอกสาร ไม่ใช่ภาษานามธรรม
- คำถามแนว "สรุป/ทั้งหมดมีกี่อย่าง/มีอะไรบ้าง/รายการ" ให้เขียน reformulated เป็น
  ประโยค "แจกแจงรายการ" ด้วยคำในเอกสาร เช่น "หัตถการที่เปิดให้บริการในระบบ ODS
  มีอะไรบ้าง" แทนที่จะเขียนว่า "จำนวน/นับประเภท" (คำแบบนับจำนวนทำให้ค้นไม่เจอ
  รายการจริง)
- sub_queries: ถ้าคำถามมีหลายประเด็นที่ต้องค้นแยกกัน ให้แตกเป็นรายการ (2-4 ข้อ)
  ถ้าเป็นคำถามประเด็นเดียว ให้ใส่ [] (ลิสต์ว่าง)
- ตอบเป็น JSON ดิบเท่านั้น ห้ามมีข้อความอื่นหรือ markdown"""


class GeminiQueryAnalyzer:
    """Pre-retrieval query understanding via Flash-Lite (cheap, structured)."""

    def __init__(self, *, api_key: str, model: str = "gemini-2.5-flash-lite") -> None:
        self._api_key = api_key
        self._model_name = model
        self._model: Any | None = None

    def _ensure_model(self) -> Any:
        if self._model is None:
            import google.generativeai as genai

            genai.configure(api_key=self._api_key)
            self._model = genai.GenerativeModel(
                self._model_name, system_instruction=_ANALYZE_PROMPT
            )
        return self._model

    async def analyze(self, query: str, history: Sequence[ChatTurn]) -> QueryAnalysis:
        import google.generativeai as genai

        model = self._ensure_model()
        convo = "\n".join(f"{t.role}: {t.content}" for t in history[-4:])
        prompt = f"บทสนทนา:\n{convo}\n\nคำถามล่าสุด: {query}"
        config = genai.types.GenerationConfig(
            temperature=0.0, response_mime_type="application/json"
        )
        try:
            result = await asyncio.to_thread(
                model.generate_content, prompt, generation_config=config
            )
        except Exception as exc:
            if _is_quota_error(exc):
                raise QuotaExceededError(str(exc)) from exc
            raise
        return self._parse(getattr(result, "text", "") or "", query)

    @staticmethod
    def _parse(raw: str, fallback: str) -> QueryAnalysis:
        # On any malformed output, fail OPEN: treat as in-scope with the
        # original query, so a parse hiccup never blocks a real question.
        try:
            data = json.loads(raw)
            reformulated = str(data.get("reformulated") or fallback).strip() or fallback
            subs_raw = data.get("sub_queries") or []
            sub_queries = [str(s).strip() for s in subs_raw if str(s).strip()]
            # A single sub-query adds nothing over the main query.
            if len(sub_queries) < 2:
                sub_queries = []
            return QueryAnalysis(
                in_scope=bool(data.get("in_scope", True)),
                reformulated=reformulated,
                sub_queries=sub_queries,
                reason=str(data.get("reason", "")),
            )
        except (json.JSONDecodeError, TypeError, ValueError):
            logging.getLogger("ods.analyze").warning("analyzer parse failed; failing open")
            return QueryAnalysis(in_scope=True, reformulated=fallback)


_CATEGORIES = ["ความรู้พื้นฐาน", "ก่อนผ่าตัด", "หลังผ่าตัด", "เทคนิค", "อื่นๆ"]
_DEPARTMENTS = [
    "ศัลยกรรมทั่วไป",
    "ศัลยกรรมส่องกล้อง/ทางเดินอาหาร",
    "จักษุ",
    "โสต ศอ นาสิก",
    "นรีเวช",
    "หลอดเลือด",
    "ภาพรวม/ไม่ระบุ",
]
_DEFAULT_TAG = ChunkTag(category="อื่นๆ", department="ภาพรวม/ไม่ระบุ")

_CLASSIFY_PROMPT = f"""คุณคือตัวช่วยจัดหมวดหมู่ข้อความจากคู่มือการผ่าตัดแบบวันเดียวกลับ (ODS)
ของโรงพยาบาลโพธาราม สำหรับแต่ละข้อความที่ให้มา ให้กำหนด 2 ป้ายกำกับ:

category (เลือก 1 จาก): {", ".join(_CATEGORIES)}
  - ความรู้พื้นฐาน = ODS/MIS คืออะไร ขอบเขต หลักการ ประโยชน์
  - ก่อนผ่าตัด = การเตรียมตัว งดน้ำงดอาหาร ตรวจเลือด/EKG นัดหมาย คัดกรอง
  - หลังผ่าตัด = ดูแลแผล พักฟื้น อาการที่ต้องกลับมาพบแพทย์ ติดตามผล กลับบ้าน
  - เทคนิค = รายละเอียดหัตถการ การดมยา เทคนิค/ความเข้าใจทางการแพทย์
  - อื่นๆ = สารบัญ บรรณานุกรม ภาระงาน บริหารจัดการ หรือไม่เข้าข้อข้างต้น

department (เลือก 1 จาก): {", ".join(_DEPARTMENTS)}
  - เลือกตามหัตถการที่ข้อความกล่าวถึง ถ้าเป็นเนื้อหาภาพรวมหลายแผนกหรือระบุไม่ได้
    ให้ใช้ "ภาพรวม/ไม่ระบุ"

ตอบกลับเป็น JSON array เท่านั้น ความยาวเท่ากับจำนวนข้อความ เรียงตามลำดับเดิม
แต่ละสมาชิกคือ {{"category": "...", "department": "..."}} ห้ามมีข้อความอื่น"""


class GeminiChunkClassifier:
    """Tags chunks with category + department via Flash-Lite, batched."""

    def __init__(
        self,
        *,
        api_key: str,
        model: str = "gemini-2.5-flash-lite",
        batch_size: int = 15,
    ) -> None:
        self._api_key = api_key
        self._model_name = model
        self._batch_size = batch_size
        self._model: Any | None = None

    def _ensure_model(self) -> Any:
        if self._model is None:
            import google.generativeai as genai

            genai.configure(api_key=self._api_key)
            self._model = genai.GenerativeModel(
                self._model_name, system_instruction=_CLASSIFY_PROMPT
            )
        return self._model

    def classify(self, texts: Sequence[str]) -> list[ChunkTag]:
        out: list[ChunkTag] = []
        for i in range(0, len(texts), self._batch_size):
            out.extend(self._classify_batch(list(texts[i : i + self._batch_size])))
        return out

    def _classify_batch(self, batch: list[str]) -> list[ChunkTag]:
        import google.generativeai as genai

        model = self._ensure_model()
        numbered = "\n".join(f"[{j}] {t[:600]}" for j, t in enumerate(batch))
        config = genai.types.GenerationConfig(
            temperature=0.0, response_mime_type="application/json"
        )
        try:
            result = model.generate_content(numbered, generation_config=config)
            data = json.loads(getattr(result, "text", "") or "[]")
        except Exception as exc:
            # Never abort a long ingest over classification: fall back to default.
            if _is_quota_error(exc):
                logging.getLogger("ods.classify").warning("quota during classify")
            else:
                logging.getLogger("ods.classify").warning("classify failed: %s", exc)
            return [_DEFAULT_TAG] * len(batch)

        tags: list[ChunkTag] = []
        for j in range(len(batch)):
            item = data[j] if isinstance(data, list) and j < len(data) else {}
            cat = item.get("category") if isinstance(item, dict) else None
            dep = item.get("department") if isinstance(item, dict) else None
            tags.append(
                ChunkTag(
                    category=cat if cat in _CATEGORIES else "อื่นๆ",
                    department=dep if dep in _DEPARTMENTS else "ภาพรวม/ไม่ระบุ",
                )
            )
        return tags
