# JMeter Performance Test — ODS RAG Chatbot

วัดประสิทธิภาพ `POST /api/chat` ด้วย Apache JMeter (เครื่องมือมาตรฐาน อ้างอิงได้ในเล่ม)

## ไฟล์

- `ods_perf.jmx` — Test Plan (เปิด/แก้ใน JMeter GUI ได้)
- `questions_jmeter.csv` — คำถาม 30 ข้อ (คั่นด้วย `|`) ที่ JMeter อ่านเข้าไปยิง
- `README_JMeter.md` — ไฟล์นี้

Test Plan มี 2 ส่วน รันต่อกัน (serialize):
1. **Baseline** — 1 user ยิงครบ 30 ข้อ ซ้ำ 5 รอบ (รวม 150 ครั้ง) เก็บ latency/percentile รายคำถาม (label = `Q1`…`Q30`)
2. **Load** — ยิงพร้อมกันหลาย user ตามเวลาที่กำหนด เก็บ throughput และ latency ตอนรับโหลด

## เตรียมก่อนรัน

1. ติดตั้ง Java 8+ และ Apache JMeter (`https://jmeter.apache.org/`)
2. เปิด backend ให้ทำงาน: `cd backend && uvicorn app.main:app`
3. ทำงานในโฟลเดอร์นี้ เพื่อให้ JMeter หา `questions_jmeter.csv` เจอ (path สัมพัทธ์)

## วิธีรันที่แนะนำ — โหมด CLI + รายงาน HTML (ใช้ในเล่มได้)

> รันจริง **ควรใช้ non-GUI** เสมอ (GUI ไว้แก้ Test Plan เท่านั้น) ผลจะเสถียรกว่า

```bash
cd benchmark
jmeter -n -t ods_perf.jmx -l results.jtl -e -o report \
  -Jhost=localhost -Jport=8000 -Jprotocol=http \
  -Jloops=150 -Jusers=8 -Jramp=8 -Jduration=60
```

- `-n` non-GUI, `-t` test plan, `-l` ไฟล์ผลดิบ, `-e -o report` สร้าง **HTML dashboard** ในโฟลเดอร์ `report/`
- เปิด `report/index.html` จะเห็น ค่าเฉลี่ย / median / p90 / p95 / p99 / throughput / error% + กราฟ
- (ถ้า `results.jtl` หรือ `report/` มีอยู่แล้ว ให้ลบก่อน หรือเปลี่ยนชื่อ)

### พารามิเตอร์ที่ปรับได้ (`-J`)

| ชื่อ | ความหมาย | ค่าเริ่มต้น |
|---|---|---|
| `host` / `port` / `protocol` | ที่อยู่ backend | localhost / 8000 / http |
| `loops` | จำนวนครั้งรวมของ Baseline (30 ข้อ × รอบ) | 150 |
| `users` | จำนวน user พร้อมกันใน Load | 8 |
| `ramp` | เวลาเร่ง user จนครบ (วินาที) | 8 |
| `duration` | ระยะเวลายิง Load (วินาที) | 60 |

อยากได้กราฟ throughput หลายระดับ concurrency (เช่น 1/2/4/8) ให้รันซ้ำหลายครั้ง
เปลี่ยน `-Jusers` แล้วแยกโฟลเดอร์ `report` ต่อรอบ เช่น `-o report_u4`

## โหมด GUI (แก้ Test Plan เท่านั้น)

```bash
jmeter -t ods_perf.jmx
```

เปิดดู/ปรับ thread group, ดูผลใน "Aggregate Report" ได้ แต่อย่าใช้ GUI รันโหลดจริง

## การอ่านผล

- **Average / Median / p95 / p99** — เวลาตอบทั้งคำถาม (มิลลิวินาที)
- **Throughput** — request/วินาที (ดูชัดในส่วน Load)
- **Error %** — สัดส่วนที่ assertion ล้มเหลว (เราเช็คว่าต้องมี event `"type": "done"`)
- ใน HTML dashboard: ดู "Statistics" (ตารางสรุป) และ "Response Times Over Time" / "Throughput"

## ข้อจำกัดสำคัญ (ต้องระบุใน methodology)

JMeter วัด **เวลาทั้งก้อนจนสตรีมจบ (total latency)** ได้ดี แต่ **จับ TTFT
(time-to-first-token) ของ SSE ไม่ได้** เพราะ HTTP Sampler รออ่านจนจบ response
ดังนั้น:

- ใช้ **JMeter** เป็นตัวเลขหลักของ total latency / throughput / error (อ้างอิงได้)
- ใช้ `benchmark_perf.py` (Python) เสริมเฉพาะค่า **TTFT** ที่ JMeter ทำไม่ได้
- ส่วนเวลาแยก stage และ token จริง อยู่ใน `PER_STAGE_TIMING_SPEC.md` (white-box)

หมายเหตุ: แต่ละ request ที่ไม่มี `conversation_id` จะสร้าง conversation ใหม่ใน
ประวัติ (Postgres) เป็นพฤติกรรมปกติของระบบ หากไม่อยากให้ประวัติรก สามารถล้าง
ภายหลัง หรือชี้ test ไปที่ฐานข้อมูล dev
