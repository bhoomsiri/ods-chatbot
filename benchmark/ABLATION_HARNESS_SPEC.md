# สเปก: RAG Ablation & Quality Evaluation Harness — สำหรับ Claude Code

> นำไฟล์นี้ไปวางให้ Claude Code ทำในเรปอจริง งานนี้แตะ `usecases/` + เพิ่ม package
> `backend/eval/` จึงต้องทำตาม Definition of Done ใน `CLAUDE.md`:
> `mypy --strict app`, `ruff check/format`, unit test ด้วย fakes, integration test
> ของ adapter ใหม่, และ safety rules §5 ต้องไม่พัง

---

## 0. สถานะข้อมูล (ตรวจแล้ว พร้อมใช้)

ชุดข้อมูลทั้งหมดอยู่ใน `benchmark/` และ **ตรงกันแล้ว** (verified):
- `benchmark/questions.json` — 30 คำถาม (ชุด gold มาตรฐาน, มี category 6 หมวด)
- `benchmark/gold.csv` — id, category, question, gold_answer, gold_pages, source_doc (ครบทั้ง 30; เลขหน้าบางข้อยังควรตรวจซ้ำ แต่ใช้ได้)
- `benchmark/oos_questions.json` — 12 คำถามนอกขอบเขต (Negative Rejection)
- คำถามใน questions.json กับ gold.csv ตรงกันครบ 30 ข้อ (id ตรง 1–1)

ให้ Claude Code **คัดลอก/อ้างไฟล์เหล่านี้** เป็น dataset ของ harness — อย่าสร้างชุดคำถามใหม่

## 1. เป้าหมาย

สร้างฮาร์เนสที่ "พิสูจน์ค่าพารามิเตอร์ (magic numbers) ด้วยข้อมูล" ผ่านการทำ
ablation แบบเปลี่ยนทีละตัว (OFAT) บนชุดคำถาม + ผลเฉลยชุดเดียวกัน แล้วรายงานเป็น
ตารางเปรียบเทียบที่เลือกค่าที่ดี/คุ้มที่สุดต่อ knob ได้อย่างมีหลักฐาน

หลักการบังคับ 3 ข้อ:
1. **OFAT** — ตรึงทุกค่าไว้ที่ baseline แล้วเปลี่ยนทีละตัว
2. **แยกชั้น retrieval / generation** — knob ที่เกี่ยวกับการค้นคืนต้องวัดด้วย
   retrieval metrics ที่ **ไม่เรียก LLM** (เร็ว ถูก deterministic) ส่วน
   generation metrics เรียกเฉพาะตอนวัด knob ของการสร้างคำตอบ
3. **Deterministic-first** — ใช้ Hit@k / Recall@k / MRR / nDCG เป็นหลักฐานหลัก
   ของ knob ค้นคืน เสริมด้วย RAGAS (LLM-judge) เท่านั้น

---

## 2. โครงสร้างที่ต้องสร้าง

```
backend/eval/
├── __init__.py
├── datasets/
│   ├── qset.json            # 30 คำถาม in-scope (คัดลอกจาก benchmark/questions.json)
│   ├── gold.csv             # ผลเฉลย (ดู schema §4) — แปลงจาก docx ของผู้ใช้
│   └── oos.json             # คำถามนอกขอบเขต (คัดลอกจาก benchmark/oos_questions.json)
├── config.py                # โหลด/ตรวจ schema ของ configs.yaml (pydantic v2)
├── configs.yaml             # นิยามการทดลอง E1–E9 (ดู §5)
├── datatypes.py             # dataclasses: EvalItem, RetrievalResult, GenResult, MetricRow
├── ingest_configs.py        # re-ingest สร้าง Qdrant collection ต่อค่า chunk/overlap
├── pipeline.py              # ประกอบ adapter จาก providers ตาม config (override settings)
├── metrics/
│   ├── retrieval.py         # hit@k, recall@k, mrr, ndcg (deterministic)
│   ├── ragas_runner.py      # faithfulness, answer_relevancy, ctx_precision, ctx_recall
│   ├── bertscore.py         # BERTScore F1 (ภาษาไทย)
│   └── rejection.py         # negative rejection rate + false-refusal rate
├── run_retrieval.py         # วน config → retrieve+rerank → retrieval metrics (ไม่เรียก LLM)
├── run_generation.py        # วน config → pipeline เต็ม → RAGAS + BERTScore + cost/latency
├── run_rejection.py         # ยิง oos → ตรวจการปฏิเสธ
├── report.py                # รวมผล → ablation_summary.xlsx + กราฟ
└── run_all.py               # orchestrator รันตามเฟส (§6)
```

**ห้ามก๊อปลอจิก pipeline** — ต้อง reuse adapter ผ่าน `app.core.providers`
(`get_store`, embedder, reranker, llm ฯลฯ) เพื่อให้ผลตรงกับ production

---

## 3. การแก้ core ที่จำเป็น (ให้น้อยที่สุด + มีเทสต์)

1. **คืน retrieved contexts ที่ใช้จริง** — RAGAS (faithfulness / context_*) ต้องใช้
   ข้อความ chunk เต็มที่ถูกส่งเข้า LLM ไม่ใช่ snippet ที่ถูกตัด ให้เพิ่มทางใดทางหนึ่ง
   โดย **ไม่ทำลาย contract เดิมของ SSE**:
   - แนวทางแนะนำ: เพิ่มเมธอด/พารามิเตอร์ใน use case `AnswerQuestion` ให้ส่งคืน
     `list[RetrievedChunk]` (id, page, source, score, text) ผ่านอีเวนต์ภายใน
     หรือ return object สำหรับโหมด eval — ต้องมี unit test ว่าโหมดปกติพฤติกรรมไม่เปลี่ยน
2. **retrieve-only entrypoint** — เพิ่มฟังก์ชันที่ทำ reformulate→retrieve→rerank→
   evidence-filter แล้ว **หยุดก่อนเรียก LLM** คืนรายการ chunk + คะแนน เพื่อให้
   `run_retrieval.py` วัด retrieval metrics โดยไม่จ่ายค่า token (สำคัญต่อ §6 เฟส 1/3)
3. **ทำให้พารามิเตอร์ override ได้ต่อ run** — `retrieval_top_k`, `rerank_candidates`,
   `rerank_top_k`, `score_threshold`, `answer_model`, `temperature`, เปิด/ปิด
   reformulation, ชื่อ collection — ต้องส่งผ่านได้ทาง config โดยไม่แก้ไฟล์ .env
   (เช่นผ่าน settings override / constructor) ตาม SOLID

---

## 4. รูปแบบข้อมูล (datasets)

### qset.json (มีแล้ว)
`[{ "id": 1, "category": "", "question": "..." }, ...]`

### gold.csv ✅ พร้อมแล้ว — `benchmark/gold.csv` (30 ข้อ ครบ answer + pages)
คอลัมน์:
| คอลัมน์ | ความหมาย | ใช้กับเมตริก |
|---|---|---|
| `id` | ตรงกับ qset | เชื่อมข้อมูล |
| `gold_answer` | คำตอบเฉลยที่ผู้เชี่ยวชาญรับรอง | RAGAS context_*, BERTScore |
| `gold_pages` | เลขหน้าเฉลย คั่นด้วย `;` (เช่น `39;151`) | Hit@k, Recall@k, MRR, nDCG |
| `source_doc` | ชื่อเอกสารต้นทาง | ตรวจ retrieval ถูกเล่ม |

> หมายเหตุ: `gold_pages` ต้อง map กับ payload `page` ใน Qdrant (มี tag page อยู่แล้ว)
> ถ้าผู้ใช้ส่ง gold เป็น docx มา ให้เขียนสคริปต์แปลง docx → gold.csv (parse คำตอบ +
> ดึงเลขหน้าใน citation รูปแบบ `[แหล่ง: ..., หน้า: NN]`)

### oos.json (มีแล้ว)
`[{ "id": "oos1", "type": "...", "question": "...", "expected": "ปฏิเสธ..." }, ...]`

---

## 5. นิยามการทดลอง (configs.yaml)

Schema ต่อ 1 config:
```yaml
- name: baseline
  kind: runtime            # runtime | index
  collection: ods_chunks_v3
  ingest: { chunk_size: 800, overlap: 120 }   # ใช้เฉพาะ kind=index
  query:
    retrieval_top_k: 20
    rerank_candidates: 20
    rerank_top_k: 8
    score_threshold: 0.3
    answer_model: gemini-2.5-flash
    reformulate: true
    temperature: 0.1
  eval: [retrieval]        # retrieval | generation | rejection (เลือกได้หลายค่า)
  repeats: 1               # generation/judge ที่สุ่ม ใช้ >=3
```

เมทริกซ์ OFAT (baseline = ค่าปัจจุบันในตาราง):

| รหัส | knob | ค่า sweep | kind | eval | เมตริกตัดสิน |
|---|---|---|---|---|---|
| E1 | chunk_size | 256,512,800,1024 (overlap 15%) | index | retrieval | Recall@k, MRR, nDCG |
| E2 | overlap | 10%,15%,20% (chunk ที่ชนะ E1) | index | retrieval | Recall@k, Ctx Precision |
| E3 | retrieval_top_k | 10,20,30 | runtime | retrieval | Recall@k + latency |
| E4 | rerank_candidates | 20,40 | runtime | retrieval | Recall@k |
| E5 | rerank_top_k | 5,8,10 | runtime | retrieval | Ctx Precision |
| E6 | score_threshold (**หลัง reranker** = cutoff ของ evidence filter บนคะแนน reranker) | 0.2,0.3,0.4,0.5 | runtime | retrieval+rejection | Ctx Precision + false-refusal |
| E7 | query transform | off, reform_only, both | runtime | retrieval+generation | Recall@k + Answer Relevancy |
| E8 | answer_model | flash, pro, flash-lite | runtime | generation | Faithfulness, AnsRel, BERTScore + cost |
| E9 | temperature | 0.0,0.1,0.3,0.5 | runtime | generation | Faithfulness + sd |

> **หมายเหตุ E6:** `score_threshold` ถูกใช้กับ **คะแนนจาก reranker หลังจัดอันดับแล้ว**
> (evidence filter) ดังนั้น Claude Code ต้องจูนค่านี้ที่จุด post-rerank: chunk ที่
> คะแนน reranker < threshold จะถูกตัดทิ้ง ถ้าตัดจนเหลือ 0 chunk → ระบบต้องปฏิเสธ
> (เชื่อมกับ Negative Rejection / false-refusal) วัด Ctx Precision/Recall ของ chunk
> ที่ "ผ่าน filter" เทียบ gold_pages

---

## 6. ลำดับการรัน (run_all.py — phased)

- **เฟส 0** ตรวจ datasets ครบ, สร้าง baseline collection ถ้ายังไม่มี
- **เฟส 1 (ถูก/เร็ว)** E3,E4,E5,E6,E7 ส่วน retrieval — retrieve-only ไม่เรียก LLM
  → ล็อกค่าที่ชนะทีละตัว
- **เฟส 2 (แพง)** E6 ส่วน rejection, E7 ส่วน generation, E8, E9 — เรียก LLM
- **เฟส 3 (แพงสุด)** E1, E2 — re-ingest collection ใหม่ต่อค่า แล้ววัด retrieval
- ทุกเฟส: เขียนผลทันที (resume ได้), ล็อกค่าที่ชนะก่อนไป knob ถัดไป

---

## 7. เมตริก (ไลบรารี + หมายเหตุ)

- **retrieval.py** (เขียนเอง, ไม่มี dependency หนัก): Hit@k, Recall@k, MRR, nDCG
  เทียบเซ็ตหน้าใน chunk ที่ดึงได้ กับ `gold_pages`
- **ragas_runner.py**: ใช้ `ragas` — faithfulness, answer_relevancy,
  context_precision, context_recall; ตั้ง judge LLM = Gemini (ของระบบ),
  embeddings = bge-m3; temperature ต่ำ
- **bertscore.py**: `bert-score` ตั้ง `lang="th"` หรือ `model_type="xlm-roberta-large"`
  (หรือ WangchanBERTa), รายงาน F1, ปิด rescale_with_baseline
- **rejection.py**: ตรวจว่าเอาต์พุตคือข้อความปฏิเสธของระบบ (เช่น "ไม่พบข้อมูลใน
  คู่มือ...") → `negative_rejection_rate` บน oos และ `false_refusal_rate` บน qset

---

## 8. ความเข้มงวดเชิงสถิติ

- generation/judge ที่สุ่ม: `repeats >= 3` รายงาน mean ± sd
- เทียบแบบ **paired** บนคำถามชุดเดียวกัน (ไม่ใช่เทียบค่าเฉลี่ยลอย ๆ)
- ใส่ bootstrap 95% CI; **ห้ามสรุปว่าต่าง** ถ้า CI เหลื่อมกัน (n=30 เล็ก)
- บันทึก seed / เวอร์ชันโมเดล / วันที่รัน ลงผลทุกครั้ง (reproducibility)

---

## 9. ผลลัพธ์

- `backend/eval/runs/<config>/results.jsonl` — ดิบรายคำถาม: question, contexts
  (id/page/score/text), answer, ทุก metric, latency, token
- `backend/eval/ablation_summary.xlsx` — 1 sheet ต่อ knob, ไฮไลต์ค่าที่ชนะ,
  คอลัมน์ cost/latency, + sheet "ค่าที่แนะนำสุดท้าย" พร้อมเหตุผล + กราฟ

---

## 10. Definition of Done

- `mypy --strict app` และ `ruff check app` ผ่าน
- unit test (fakes, ไม่ต่อเน็ต) สำหรับทุกฟังก์ชันใน `metrics/` (ตรวจสูตร hit@k/mrr/
  ndcg ด้วยเคสที่คำนวณมือได้) และสำหรับ `config.py` (validate schema)
- unit test ยืนยันว่าโหมดปกติของ `AnswerQuestion` พฤติกรรมไม่เปลี่ยนหลังเพิ่มการคืน contexts
- integration test เล็ก: รัน 1 config retrieval-only กับ Qdrant ของ docker-compose
- safety rules §5 ใน CLAUDE.md ยังครบ

## 11. เกณฑ์ความสำเร็จ

รัน `python -m backend.eval.run_all` แล้วได้ `ablation_summary.xlsx` ที่บอก "ค่าที่ดี
ที่สุดต่อ knob พร้อมหลักฐานเชิงตัวเลข + cost/latency" และสามารถตอบกรรมการได้ว่า
ทำไมเลือก chunk/overlap/k/threshold/model/temperature ค่านั้น ๆ
