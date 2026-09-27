# สเปกงาน: Per-stage timing & token usage (white-box) — สำหรับ Claude Code

> นำไฟล์นี้ไปวางให้ Claude Code ทำในเรปอจริง งานนี้แตะ `usecases/` + adapter จึง
> ต้องทำตาม Definition of Done ใน `CLAUDE.md` (mypy --strict, ruff, unit tests ด้วย fakes)

## เป้าหมาย

เก็บ "เวลาแยกแต่ละ stage" และ "จำนวน token จริง" ของแต่ละคำถาม เพื่อใช้กับ
performance test ให้แม่นกว่าการวัด black-box ภายนอก ปัจจุบันวัดได้แค่ TTFT/total
และประเมิน output token แบบหยาบ — งานนี้จะได้:

1. เวลาแยก stage: `query_reformulation`, `retrieval`, `rerank`, `generation`
2. token usage จริงจาก Gemini: `prompt_token_count`, `candidates_token_count`
   (อ่านจาก `usage_metadata` ของ response/last chunk ใน `gemini_llm.py`)
3. ช่องทางส่งออกตัวเลขเหล่านี้โดย **ไม่กระทบ contract เดิม** ของ SSE

## ข้อกำหนดเชิงสถาปัตยกรรม (ห้ามผิด)

- **อย่าแก้ port signature** ใน `domain/ports.py` แบบ breaking ถ้าเลี่ยงได้
  ให้เพิ่มเป็น field ใหม่ที่ optional แทน
- การจับเวลาเป็น cross-cutting concern — ทำใน `usecases/answer.py` (ชั้น
  orchestration) ด้วย `time.perf_counter()` ครอบแต่ละ stage ไม่ใส่ลอจิกเวลา
  ลงใน adapter
- token usage เป็นเรื่องของ provider — ให้ `gemini_llm.py` คืนค่า usage ออกมา
  ผ่าน entity/อีเวนต์ ไม่ให้ usecase ไปรู้จัก SDK ของ Gemini เอง

## แนวทางที่แนะนำ

1. เพิ่ม entity ใหม่ใน `domain/entities.py`:

   ```python
   @dataclass(frozen=True)
   class StageTimings:
       reformulate_ms: float
       retrieve_ms: float
       rerank_ms: float
       generate_ms: float
       prompt_tokens: int | None = None
       output_tokens: int | None = None

   @dataclass(frozen=True)
   class MetricsEvent:
       timings: StageTimings
   ```

2. ใน `usecases/answer.py` ครอบเวลาแต่ละ stage ด้วย `perf_counter()` สะสมค่า
   แล้ว **yield `MetricsEvent` เป็นอีเวนต์สุดท้ายก่อน done** (เพิ่มชนิดอีเวนต์
   ใหม่ ไม่แก้ของเดิม)

3. ให้ `LLMPort.generate(...)` (หรือ adapter `gemini_llm.py`) แนบ usage กลับมา
   เช่นคืน `tuple[stream, UsageGetter]` หรือ set ลง context object — โดยอ่านจาก
   `response.usage_metadata` ของ google-genai

4. ใน `api/routers/chat.py` เพิ่มการ handle `MetricsEvent`: ส่งออกเป็น SSE
   `{"type": "metrics", ...}` **เฉพาะเมื่อ** request ส่ง header `X-Debug-Metrics: 1`
   (หรือ flag ใน settings) เพื่อไม่ให้ frontend production เห็น

5. อัปเดต `benchmark_perf.py` (ในโฟลเดอร์นี้) ให้ส่ง header debug แล้วอ่าน event
   `metrics` มาบันทึกลงผลด้วย — เพิ่มคอลัมน์ `reformulate_ms / retrieve_ms /
   rerank_ms / generate_ms / prompt_tokens / output_tokens`

## เทสต์ที่ต้องเพิ่ม (DoD)

- unit test ใน `tests/unit`: ใช้ fake LLM/retriever ตรวจว่า usecase yield
  `MetricsEvent` ที่มี 4 stage และค่าเวลาเป็นบวก
- unit test: เมื่อไม่มี header debug router ต้อง **ไม่** ส่ง event `metrics`
- `mypy --strict app` และ `ruff check app` ต้องผ่าน

## เกณฑ์ความสำเร็จ

รัน `python benchmark/benchmark_perf.py` แล้วได้คอลัมน์เวลาแยก stage + token จริง
ใน `perf_summary.xlsx` และ safety rules เดิมใน `CLAUDE.md` §5 ยังทำงานครบ
