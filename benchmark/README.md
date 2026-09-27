# Performance Benchmark — ODS RAG Chatbot

ชุดเครื่องมือวัด **ประสิทธิภาพระบบ** (ความเร็ว / throughput / ต้นทุนโดยประมาณ) ของ
endpoint `POST /api/chat` แบบ black-box คือยิงผ่าน API จริงโดยไม่แก้โค้ด backend

## ไฟล์ในโฟลเดอร์นี้

- `benchmark_perf.py` — สคริปต์หลัก
- `questions.json` — ชุดคำถามทดสอบ 30 ข้อ (แก้/เพิ่มได้)
- `README.md` — ไฟล์นี้
- `PER_STAGE_TIMING_SPEC.md` — สเปกสำหรับนำไปสั่ง Claude Code ทำส่วน per-stage timing (white-box)

## วิธีรัน

1. เปิด backend ให้ทำงานอยู่ และให้ Qdrant / Gemini พร้อมใช้งาน

   ```bash
   cd backend && uvicorn app.main:app
   ```

2. ติดตั้ง dependency ของตัว benchmark

   ```bash
   pip install httpx openpyxl
   ```

3. แก้ค่าในส่วน `CONFIG` ที่หัวไฟล์ `benchmark_perf.py` ให้ตรงกับระบบคุณ —
   อย่างน้อยคือ `BASE_URL`, `MODEL_NAME`, และ **ราคาโมเดลปัจจุบัน**
   (`PRICE_OUTPUT_PER_1M_USD`) ซึ่งต้องไปดูจากหน้า pricing ของ Google เอง

4. รัน

   ```bash
   cd benchmark && python benchmark_perf.py
   ```

## ผลลัพธ์

- `perf_raw.csv` — ข้อมูลดิบทุก request ทุกข้อทุกรอบ
- `perf_summary.xlsx` — สรุปพร้อมกราฟ มี 4–5 sheet:
  - **Config** — ค่าที่ใช้รัน
  - **PerQuestion** — เวลาเฉลี่ย/ p95 รายคำถาม + กราฟแท่ง
  - **Overall** — total latency / TTFT / stream + ต้นทุนโดยประมาณ
  - **LoadTest** — throughput และ latency ตามระดับ concurrency + กราฟ

## เมตริกที่วัด

| เมตริก | ความหมาย |
|---|---|
| **TTFT** | เวลาตั้งแต่ส่งคำถามจนได้ token แรก (สำคัญกับความรู้สึก "เร็ว" ของผู้ใช้แบบ streaming) |
| **total latency** | เวลาจนระบบตอบจบ (event `done`) |
| **stream duration** | เวลาตั้งแต่ token แรกถึงสุดท้าย |
| **throughput** | req/s เมื่อยิงพร้อมกันหลายคน |
| **out_tokens_est / cost** | จำนวน token ของคำตอบและต้นทุนโดยประมาณ |

แนะนำให้รายงานเป็น mean ± sd และ p95/p99 (สคริปต์คำนวณให้แล้ว) และตัด warmup
รอบแรกออกเพื่อกัน cold start

## ข้อจำกัดของการวัดแบบ black-box (สำคัญ)

- **ต้นทุน input token วัดไม่ได้** จากภายนอก เพราะ prompt ที่ส่งเข้า Gemini รวม
  context ที่ retrieve มา (≈ 8 chunk) ซึ่ง client มองไม่เห็น สคริปต์จึงประเมิน
  เฉพาะ **output token** และใช้ตัวคูณหยาบ ๆ (`CHARS_PER_OUTPUT_TOKEN`)
- **แยกเวลาแต่ละ stage ไม่ได้** (retrieval / rerank / generation) จากภายนอก
  เห็นได้แค่ TTFT กับ total

ถ้าต้องการตัวเลขที่แม่นทั้ง **ต้นทุนจริง** และ **เวลาแยก stage** ต้องทำแบบ
white-box (ฝังการจับเวลา + อ่าน `usage_metadata` ของ Gemini ในตัว backend) ซึ่ง
แตะโค้ดหลักและต้องมีเทสต์ตาม Definition of Done — รายละเอียดอยู่ใน
`PER_STAGE_TIMING_SPEC.md` เอาไปวางให้ Claude Code ทำในเรปอได้เลย
