# สเปก: เปรียบเทียบ Vector RAG vs GraphRAG (KG) — พิสูจน์ "KG over-engineering" สำหรับ Claude Code

> เป้าหมาย: หาหลักฐานเชิงตัวเลขตอบ comment กรรมการ "ทำไมไม่ใช้ Knowledge Graph"
> โดยเทียบระบบ Vector RAG ปัจจุบัน (มีผลครบแล้ว) กับ GraphRAG baseline บนคลังเอกสาร +
> ชุดคำถาม + ผลเฉลย + เมตริก **ชุดเดียวกัน** (apples-to-apples)

## สมมุติฐาน (ตั้งให้ชัด — ต้องพิสูจน์ ไม่ตั้งธง)
"สำหรับโดเมน ODS Q&A, GraphRAG **ไม่ให้ผลคุณภาพดีขึ้นอย่างมีนัยสำคัญ** เหนือ hybrid
vector RAG ขณะที่ **ต้นทุน/ความซับซ้อนสูงกว่าชัดเจน** → เป็น over-engineering ในบริบทนี้"
- Over-engineering พิสูจน์เมื่อ: ΔQuality (KG − Vector) ≈ 0 หรือติดลบ + CI เหลื่อมกัน **และ** ΔCost/Complexity สูงมาก
- ถ้า KG ชนะจริงอย่างมีนัยสำคัญ → รายงานตามนั้น (ความซื่อสัตย์เชิงวิจัย)

## 0. การแยกงานออกจากต้นฉบับ (ISOLATION — บังคับสูงสุด)
> งานทดสอบ KG นี้ **ห้ามแตะ/แก้/ทำให้พังงานต้นฉบับเดิมเด็ดขาด** ต้นฉบับถูกแตะแบบ read-only เท่านั้น
> ถ้าข้อใดขัดกับหลักนี้ ให้หยุดและถามก่อน

**อ่านอย่างเดียว (ห้ามเขียนทับ/ลบ/แก้):**
- [ ] `ods_chunks_v3` = **query + payload filter เท่านั้น** ห้าม `upsert`/`delete`/สร้าง collection ใหม่/แก้ payload index
- [ ] `benchmark/gold.csv`, `benchmark/questions.json`, `backend/eval/runs/*` เดิม, `backend/app/*` = อ่านอย่างเดียว
- [ ] ถ้าต้อง post-filter ผลเดิม → **copy** ไปโฟลเดอร์ใหม่ ห้ามเขียนทับไฟล์เดิม

**ของใหม่แยกหมด (สร้างใหม่ ไม่ปนของเดิม):**
- [ ] โค้ด: `backend/eval/kg_compare/` เท่านั้น — **ห้ามแก้ `backend/app/`** (นี่คือ experiment ไม่ใช่ runtime)
- [ ] ผลรัน: `backend/eval/runs/kg_compare/{vector_subset,graphrag}/`
- [ ] KG store: path/namespace ของ LightRAG แยกเอง (เช่น `backend/eval/kg_compare/kg_store/`)
- [ ] รายงาน: **ชีตใหม่หรือไฟล์ใหม่** (`kg_comparison.xlsx`) — ห้ามเขียนทับ `final_comparison.xlsx` เดิม
- [ ] แนะนำทำบน **git branch แยก** (เช่น `exp/kg-compare`)

**Rollback:** ลบ `backend/eval/kg_compare/` + KG collection ทิ้ง → ต้นฉบับกลับมาเหมือนเดิม 100% (เพราะไม่เคยถูกแก้)

## ใช้ของเดิมแบบ read-only + subset (ประหยัด ไม่ ingest ใหม่)
- **ฝั่ง Vector = ไม่ ingest ใหม่**: subset คือ "มุมมองที่กรองแล้ว" ของ `ods_chunks_v3` เดิม ใช้ **payload filter** (`source_doc ∈ subset`) ตอน query — ใช้ embeddings/chunk เดิมทั้งหมด
- **ฝั่ง KG = build ครั้งเดียวบน subset เท่านั้น** (KG ไม่เคยมีมาก่อน จึงต้องสร้าง แต่ subset เล็ก = ถูก) — นี่คือ "ต้นทุนของ KG" ที่จะรายงาน
- เทียบด้วย gold + เมตริก + judge (Claude) เดิม บนคำถามที่กรองแล้วชุดเดียวกัน

---

## เฟส 0 — เลือก subset + กรองคำถาม (กฎกลาง กัน cherry-pick)
- เลือกเอกสาร **1–2 เล่มที่ครอบคลุมคำถามมากที่สุด** (นับจาก `source_doc` ใน gold.csv) — ห้ามเลือกโดยดูว่าเอกสารไหนทำให้ KG ดูดี/แย่
- กรอง 30 ข้อ → เหลือเฉพาะข้อที่ `source_doc`/`gold_pages` อยู่ใน subset (คาดเหลือ ~12–18 ข้อ) บันทึกจำนวน + รายการ id ไว้
- บันทึกกฎการเลือก subset ลง provenance (เพื่อ reproduce)

## เฟส 1 — Vector subset (query ของเดิม, ไม่ ingest)
- query `ods_chunks_v3` เดิม + **Qdrant payload filter** `source_doc ∈ subset` → ยิงคำถามที่กรองแล้ว
- answer model = **gemini-2.5-flash**, safety prompt เดิม, top-k บันทึกไว้
- เขียนผล → `runs/kg_compare/vector_subset/results.jsonl` (schema = gen_*)
- (ทางเลือกถูกกว่า: retrieval metrics บางตัว post-filter จากผล baseline เดิมได้ แต่ **copy ออกมา** ไม่แก้ของเดิม)

## เฟส 2 — Build GraphRAG (LightRAG) บน subset + รัน
- Framework: **LightRAG** (`lightrag-hku`) — GraphRAG ที่ตีพิมพ์+maintained (แฟร์) และถูกกว่า MS GraphRAG
- **คลัง = เอกสาร subset ชุดเดียวกับเฟส 0** | embeddings = **bge-m3** | answer model = **gemini-2.5-flash** (เท่า vector)
- entity/relation extraction: ผ่าน **fairness gate §6.5** ก่อน (โมเดลพอใช้ + spot-check กราฟไทย ก่อนรันจริง)
- store แยกใน `kg_compare/kg_store/` | โหมด **hybrid**
- บันทึกตอน build: เวลา index, จำนวน LLM calls, ต้นทุน ($), จำนวน node/edge
- ยิงคำถามชุดเดียวกับเฟส 1 → `runs/kg_compare/graphrag/results.jsonl` + latency/LLM-calls ต่อข้อ

## เฟส 3 — วัดด้วยเมตริก + gold ชุดเดียวกัน (harness เดิมแบบ read-only)
- เรียก harness เดิม (`score_ragas.py`, `text_metrics.py`, ฯลฯ) แบบ **read-only ชี้ input ไป `runs/kg_compare/`** — ไม่แก้สคริปต์เดิม (ถ้าต้องปรับ ให้ wrap ใน `kg_compare/` แทน)
  - Context Precision / Context Recall (RAGAS + **Claude judge เดิม** เพื่อเทียบตรง)
  - Faithfulness, Answer Relevancy (judge เดียวกับที่ใช้กับ Vector RAG)
  - BLEU, BERTScore (เทียบ gold_answer เดิม) | Precision@k/Recall@k = **src-level** เท่านั้น (+หมายเหตุ)
- ออกเป็นคอลัมน์ `vector_subset` vs `graphrag` — ตาราง Vector vs KG (บนคำถาม subset ชุดเดียวกัน)

## 4. ตาราง "ต้นทุนของความซับซ้อน" (แกนที่ 2)
| มิติ | Vector RAG | GraphRAG (KG) |
|---|---|---|
| เวลา index build | (มี) | (วัด) |
| ต้นทุน index ($ จาก LLM extraction) | ~0 | (วัด) |
| query latency (p50) | (มี) | (วัด) |
| LLM calls / คำถาม | (มี) | (วัด) |
| จำนวน component / บรรทัดโค้ด | (นับ) | (นับ) |
| failure mode ใหม่ | — | entity/relation extraction ผิด → เสี่ยง safety |

## 5. Domain-fit (แกนที่ 3)
- tag คำถาม 30 ข้อ: single-hop vs multi-hop (KG เด่นเฉพาะ multi-hop) — คาดว่า multi-hop มีน้อยมาก (หมวด 6 ข้อ 26/27/29 ใกล้ที่สุด) → จุดแข็ง KG แทบไม่ถูกใช้
- (ทำแยกได้ ไม่ใช้เครดิต)

## 6. สถิติ + เกณฑ์ตัดสิน
- เทียบแบบ **paired** บนคำถามชุดเดียว, รายงาน mean ± sd + bootstrap 95% CI
- **ห้ามสรุปว่า KG ดีกว่า/แย่กว่า** ถ้า CI เหลื่อมกัน (n=30 เล็ก)
- สรุป over-engineering ตามเกณฑ์ในหัวข้อสมมุติฐาน (ΔQuality vs ΔCost)

## 6.5 การรับประกันความแฟร์ต่อ LightRAG (บังคับ — ทำก่อนเชื่อผลใด ๆ)
> เป้าหมาย: ตัด "เสียเปรียบแบบไม่แฟร์" ออกให้หมด เพื่อให้ช่องว่างที่เหลือ = architecture-domain fit จริง
> ถ้าข้อใดข้อหนึ่งไม่ผ่าน **ห้ามรายงานผลเทียบ** จนกว่าจะแก้

### A. ตัวแปรที่ต้อง "เท่ากันเป๊ะ" ทั้งสองระบบ (คุมให้เหลือต่างเฉพาะชั้น retrieval/graph)
- [ ] answer model = **gemini-2.5-flash**, temperature เท่ากัน, system prompt เท่ากัน (safety prompt เดิม)
- [ ] embeddings = **bge-m3** เดียวกัน (LightRAG เสียบ embedding เดียวกัน ไม่ใช้ default)
- [ ] คลังเอกสาร = ไฟล์ต้นฉบับ ODS ชุดเดียวกัน (ก่อน chunk) — ห้ามให้ฝั่งใดได้เอกสารมากกว่า
- [ ] eval set = questions.json 30 ข้อ + gold.csv เดิม | judge = **Claude เดียวกัน** | เมตริกนิยามเดียวกัน
- [ ] top-k / จำนวน context ที่ป้อนเข้า generator ตั้งให้เทียบเคียงกัน (เช่น k ใกล้กัน) บันทึกค่าไว้

### B. ให้ LightRAG ได้ "โอกาสดีที่สุด" (ไม่ handicap)
- [ ] **entity/relation extraction ใช้โมเดลระดับพอใช้** (อย่างน้อย gemini-2.5-flash; ถ้าใช้ flash-lite/Haiku เพื่อคุมงบ ต้องผ่าน gate C ก่อน)
- [ ] เปิดโหมด **hybrid** (dual-level: local + global) ซึ่งเป็นจุดแข็งของ LightRAG ไม่ใช่โหมด naive
- [ ] ตั้ง chunk size / param ของ LightRAG อย่างสมเหตุผลสำหรับไทย (ไม่ใช้ default อังกฤษดิบ ๆ)
- [ ] ถ้าปรับได้: prompt สกัด entity ให้รองรับบริบทการแพทย์/ภาษาไทย

### C. Gate คุณภาพกราฟภาษาไทย (ทำก่อนรัน 30 ข้อ)
- [ ] spot-check กราฟที่สกัดได้ **≥ 15 entity + 15 relation** ด้วยตา — entity ไทยต้องถูกต้อง/ไม่หลุด/ไม่แตกคำ
- [ ] ถ้า extraction ไทยพัง → เปลี่ยนโมเดล extraction ที่แรงขึ้น แล้วทำซ้ำ (อย่ารันต่อทั้งที่กราฟพัง)
- [ ] บันทึกจำนวน node/edge + ตัวอย่างกราฟ 1 หน้าไว้เป็นหลักฐานว่า "ทำ KG อย่างตั้งใจแล้ว"

### D. แยกเหตุของช่องว่างให้ชัดในรายงาน (กันการปนกัน)
- [ ] ถ้า LightRAG แพร่เพราะ **Thai extraction เปราะ** → รายงานเป็น "ต้นทุน/ความเสี่ยงที่ KG เพิ่ม" (dependency ใหม่) **แยกบรรทัด**
- [ ] ถ้า LightRAG แพ้เพราะ **โดเมน single-hop** → รายงานเป็นข้อสรุป domain-fit
- [ ] **ห้ามรวมสองเหตุนี้เข้าด้วยกัน** และห้ามอ้าง over-engineering จากเหตุ Thai-extraction เพียงอย่างเดียว

### E. คู่เทียบฝั่ง Vector = production/best config
- [ ] เทียบกับ **baseline บน ods_chunks_v3** (production, ผลครบ) — คู่เทียบที่แข็งที่สุดอย่างซื่อสัตย์ ไม่ใช่ config อ่อน

## 6.7 สถาปัตยกรรม SOLID / ports-adapters (ตาม CLAUDE.md — บังคับ)
> "Never edit a use case to add a vendor" — LightRAG = **adapter ใหม่** ที่ implement port เดิม ไม่ใช่สคริปต์พันกับ business logic
- [ ] **LightRagRetriever** implement `Retriever` port เดิมใน `domain/` (เหมือน Qdrant retriever) → use case orchestration เดิมใช้ได้โดยไม่แก้
- [ ] **KgIndexBuilder** แยกคลาส (Single Responsibility): สร้าง/สกัดกราฟ คนละตัวกับการ retrieve คนละตัวกับการให้คะแนน
- [ ] wiring ผ่าน **DI/Depends** — use case ขึ้นกับ abstraction ไม่ขึ้นกับ LightRAG (concrete)
- [ ] ถ้าจะใช้ generation ในตัว LightRAG เอง ต้อง wrap ผ่าน port ให้ชัดว่าเป็นคนละ config (โดยปกติ: ให้ adapter คืน `contexts` แล้วส่งเข้า **generator เดิม** เพื่อคุม answer model ให้เท่ากับ vector ตาม §6.5)
- [ ] **โค้ดทั้งหมดอยู่ใน `backend/eval/kg_compare/`** — port ที่ implement อ้างอิงจาก `domain/` เดิมได้ (อ่านอย่างเดียว) แต่ห้ามแก้ `domain/`/`usecases/`/`app/`
- [ ] DoD: mypy --strict, ruff, **unit test ด้วย fake ของ port** (ไม่เรียก network), integration test ของ adapter จริง

## 7. Threats to validity (ต้องเขียนในเล่ม)
- ต้อง build KG ด้วย framework ที่ maintained + ตั้งค่าอย่างสมเหตุผล (ไม่งั้น "แพ้เพราะทำไม่ดี")
- คุม answer model + embeddings + judge ให้เหมือน Vector RAG ทุกจุด (เปลี่ยนเฉพาะ retrieval/graph)
- ระบุว่า entity extraction ภาษาไทยของ LightRAG มีข้อจำกัด — เป็นส่วนหนึ่งของ "ต้นทุน/ความเสี่ยง" ที่ต้องรายงาน

## Output (แยกจากต้นฉบับทั้งหมด)
- `runs/kg_compare/{vector_subset,graphrag}/results.jsonl` + `runs/kg_compare/_summary_kg.json`
- **ไฟล์ใหม่ `benchmark/kg_comparison.xlsx`** (ห้ามทับ `final_comparison.xlsx` เดิม): ชีตเทียบคุณภาพ Vector vs KG + ชีตต้นทุน/ความซับซ้อน + ชีต domain-fit + ชีต provenance
- ย่อหน้าสรุปสำหรับลงเล่ม (เหตุผลว่าทำไม ODS ไม่ต้องใช้ KG + ตัวเลขสนับสนุน)

## DoD (ถ้าอยู่ในเรปอ)
- **ISOLATION §0 ผ่านครบ** — ยืนยันด้วย `git status`/diff ว่าไม่มีไฟล์ต้นฉบับเดิมถูกแก้ (เฉพาะ `backend/eval/kg_compare/` + ไฟล์ใหม่)
- mypy/ruff ผ่านบนโค้ดใหม่, unit test ของ adapter/สคริปต์ใหม่, **ไม่แตะ `backend/app/` และ pipeline เดิม**
- ยืนยัน `ods_chunks_v3` ไม่ถูกเขียน/ลบ (query-only) | safety §5 ไม่กระทบ
- บันทึก provenance (LightRAG เวอร์ชัน, โมเดล extraction/answer/judge, ต้นทุน, กฎเลือก subset, รายการ id คำถาม)

## 8. Performance test — JMeter twin-endpoint (Vector vs KG, แฟร์)
> เป้าหมาย: วัด perf (TTFT, latency p50/p95, throughput, error rate) ของ **retrieval สองแบบ**
> โดยคุม serving stack ให้เหมือนกันเป๊ะ — ต่างแค่ชั้น retrieval — เพื่อไม่ให้ความต่างมาจาก
> "endpoint หนึ่งเขียนดีกว่า" (§6.5 fairness ยังบังคับใช้)

### 8.1 Isolated twin-endpoint server (ต่อใหม่ ไม่แตะ production)
- ไฟล์ใหม่ **`backend/eval/kg_compare/serve_compare.py`** — FastAPI แยก รันคนละพอร์ต (เช่น **8100**)
- **ห้ามแก้ `backend/app/`**; นำเข้า `generate()` เดิมแบบ read-only ได้ (reuse ตัวเดียวกัน) หรือ wrap thin ใน kg_compare/
- 2 endpoint ที่ **ต่างกันแค่ retriever**:
  - `POST /vec/chat` → Qdrant subset retrieval (payload filter `source ∈ subset`, reuse `subset_store.py`)
  - `POST /kg/chat` → LightRAG retrieval (mode `mix`, reuse `lightrag_retriever.py`)
- **คุมให้เท่ากันทั้งคู่**: answer model, prompt, top-k, และ **สตรีมแบบเดียวกัน (SSE)** เพื่อให้ TTFT เทียบได้ตรง
- request schema เดียวกับ `/api/chat` (JMeter CSV เดิมใช้ได้)

### 8.2 JMeter plan (ไฟล์ใหม่ ไม่แตะ ods_perf.jmx เดิม)
- **`benchmark/ods_perf_kg.jmx`** — clone จากของเดิม, parametrize `HOST/PORT/PATH` ให้ยิงได้ทั้ง `/vec/chat` และ `/kg/chat`
- ใช้ `questions_jmeter.csv` เดิม (คำถามชุดเดียวกันทั้งสอง endpoint = แฟร์)
- **load เบา (คุมต้นทุน Gemini)**: Baseline 1 user (~5 loop) + Load ~5 concurrent × loop น้อย
- **warmup ก่อนวัด**: ยิง 1-2 request ทิ้ง (ตัด cold-start ~16-24s ที่เห็นในรัน offline) แล้วค่อยเก็บผล
- รันสองรอบ (vec แล้ว kg) ด้วย thread group เดียวกัน → เทียบตรง

### 8.3 Output + คุมต้นทุน
- ผลดิบ (JTL) → `backend/eval/runs/kg_compare/perf/` (gitignore) | สรุป → **`benchmark/kg_perf_report.md`** (ไฟล์ใหม่)
- ตารางเทียบ: TTFT p50/p95, total latency p50/p95, throughput (req/s), error rate, ค่าประมาณ Gemini calls/ต้นทุน
- ประเมินจำนวน request รวม × ต้นทุนต่อ call ก่อนรัน แล้วรายงาน

### 8.4 Fairness + threats (เขียนกำกับผล)
- serving stack เดียว, generator/model/prompt/สตรีมเหมือนกัน, ต่างแค่ retrieval → perf gap = ผลของสถาปัตยกรรม retrieval
- n load เบา → เป็น indicative ไม่ใช่ stress test เต็ม; ระบุตรง ๆ
- ต่อยอดจากผล offline เดิม (latency_ms ต่อข้อ) เพื่อ cross-check ทิศทาง

### 8.5 DoD (isolation)
- `git diff` ยืนยันไม่มีไฟล์ `backend/app/`/ods_perf.jmx เดิมถูกแก้ | โค้ดใหม่อยู่ใน kg_compare/ + ไฟล์ jmx/report ใหม่
- ยืนยัน `ods_chunks_v3` query-only | server ทดสอบดับได้โดยไม่กระทบ production

## เกณฑ์สำเร็จ
ได้ตารางเทียบ Vector vs KG ครบ (คุณภาพ + ต้นทุน + domain-fit + **perf จาก JMeter twin-endpoint**)
พร้อมสถิติ CI ที่ทำให้ "ตอบกรรมการเรื่อง KG ได้ด้วยหลักฐาน" ไม่ใช่คำอ้าง
