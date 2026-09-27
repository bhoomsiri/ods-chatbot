# สเปก: เพิ่มเมตริกที่ขาด แบบ score-only — สำหรับ Claude Code

> **ห้าม re-run ablation, ห้าม re-ingest, ห้าม re-retrieve, ห้าม re-generate**
> คำนวณเมตริกเพิ่ม "ทับผลที่รันไว้แล้ว" ใน `backend/eval/runs/*/results.jsonl`
> ต้องทำตาม DoD ใน CLAUDE.md (mypy --strict, ruff, unit test ด้วย fakes)
>
> **หลักการสำคัญ:** ใช้ **ไลบรารีมาตรฐานที่ validate แล้ว** (sacreBLEU, bert-score,
> official `ragas`) ห้ามเขียนสูตรเอง เพื่อให้ได้ "ค่าตามนิยามจริง" ไม่ใช่ค่าประมาณ

## ข้อจำกัด collection (สำคัญ)
- collection ทดสอบ E1/E2 **ถูกลบแล้ว** เหลือแต่ `ods_chunks_v3` (production)
- Context Precision/Recall + dump chunk-text ทำได้เฉพาะ config บน `ods_chunks_v3`:
  `baseline, E3_*, E4_*, E5_*, E6_*, E7_*, gen_*` → E1/E2 = `N/A (collection removed)`
- Precision@k, BLEU, BERTScore **ไม่ใช้ Qdrant** → ทำได้ทุก config

## Judge = Claude (cross-family, ลด self-bias)
- answer model = Gemini → **ใช้ Claude เป็น judge** (คนละค่าย ลด self-preference bias ได้ดีสุด)
- เสียบผ่าน RAGAS ด้วย LangChain `ChatAnthropic` (เช่น `claude-sonnet` / `claude-opus`) — ต้องมี Anthropic API key
- embeddings สำหรับ RAGAS = bge-m3 (ของระบบ), temperature 0
- ใช้ Claude judge กับทั้ง Context Precision/Recall และ re-judge Faithfulness/Answer Relevancy

---

## เมตริกที่ต้องเพิ่ม

### 1) Precision@k — deterministic (ทุก config, ไม่ใช้ Qdrant/LLM)
- `precision@k = (#relevant ใน top-k)/k` ทั้ง page-key และ source-key
- จาก `reranked` + `gold_pages`/source ที่เซฟไว้ | output 0–1

### 2) BLEU — `sacrebleu` (ไทยต้องตัดคำก่อน)
- candidate=`answer`, reference=`gold_answer`
- **ตัดคำไทยด้วย `pythainlp.word_tokenize` ก่อน** → sacreBLEU `tokenize="none"` (ห้าม '13a' default)
- corpus-level BLEU (0–100) + BLEU-1..4, smoothing สำหรับคำตอบสั้น

### 3) BERTScore — `bert-score` (โมเดลไทย)
- `model_type="xlm-roberta-large"` หรือ WangchanBERTa, `lang="th"`, `rescale_with_baseline=False`, รายงาน F1
- หมายเหตุ: ค่าจะกระจุกสูง (~0.6–1.0) → ตีความเชิงเปรียบเทียบ

### 4) Context Precision / Context Recall — **official `ragas`** + Claude judge
- input: `question`, `contexts`=ข้อความ chunk เต็ม (fetch จาก Qdrant ด้วย id), `reference`=`gold_answer`
- เฉพาะ config บน ods_chunks_v3 (E1/E2 = N/A) | output 0–1

### 5) Re-judge Faithfulness / Answer Relevancy — **official `ragas`** + Claude judge บน answer เดิม
- input: `question`, `answer` (เซฟไว้), `contexts` (fetch by id)
- รายงาน **คู่กับค่าเดิม (Flash-judge)** เพื่อดู self-bias + correlation ระหว่างสอง judge

---

## การรับประกันความถูกต้อง (ให้ได้ "ค่าตามที่ต้องการจริง")
- **A. ปักหมุดเวอร์ชัน**: sacrebleu, pythainlp, bert-score, ragas, langchain-anthropic (RAGAS เปลี่ยน schema บ่อย → map ฟิลด์ให้ตรงเวอร์ชัน)
- **B. unit test ค่าที่คำนวณมือได้**: precision@k (`[1,0,1]`,k=2→0.5), BLEU จาก token list, ยืนยันตัวตัดคำไทยทำงาน
- **C. golden sanity**: identical→BLEU 100/BERTScore~1/faithfulness~1 ; unrelated→BLEU~0 แต่ BERTScore ไทยมี floor (~0.6) ไม่ใช่ 0 ; context มี gold ชัด→recall สูง
- **D. assert ช่วงค่า** ∈ [0,1]/[0,100] มิฉะนั้น raise (กัน NaN เงียบ)
- **E. provenance**: บันทึกชื่อ+เวอร์ชันไลบรารี, judge model (Claude ...), embeddings, โมเดล BERTScore ลงผล
- **F. spot-check**: dump 3 ข้อต่อเมตริก (input+score) ให้ตรวจด้วยตาก่อนเชื่อค่าเฉลี่ย
- **G. assert judge ≠ answer family** (judge ต้องเป็น Claude ไม่ใช่ Gemini)

---

## Output — ต้องมี "ผลการเทียบ" เหล่านี้ครบ
1. **ตารางเทียบทุก metric ต่อ config** (retrieval + generation + BLEU/BERTScore/Context + judge ใหม่) ไฮไลต์ค่าที่ชนะต่อ knob
2. **retrieved-vs-gold รายคำถาม พร้อมข้อความ chunk จริง** (id/page/source/score/text) เทียบกับ gold_answer/gold_pages
3. **เทียบข้อเดียวกันข้ามหลาย config** (เลือกข้อตัวอย่าง เช่น ข้อ 1/28/30 ดูว่าค่าเปลี่ยนตาม knob อย่างไร)
4. **เทียบ judge เดิม (Gemini-Flash) vs judge ใหม่ (Claude)** ต่อข้อ + correlation (Pearson/Spearman) + Bland–Altman/scatter
5. **ช่องรอ correlation กับคะแนนผู้เชี่ยวชาญ** (เติมเมื่อผู้เชี่ยวชาญคนที่ 3 มา)
- ออกเป็น Excel หลาย sheet + provenance sheet

## DoD
- `mypy --strict app`, `ruff` ผ่าน | unit tests ข้อ B/C ผ่าน
- ไม่มี re-ingest/re-run (อ่าน runs/ + fetch-by-id เท่านั้น) | safety §5 ไม่กระทบ

## เกณฑ์สำเร็จ
ได้เมตริกครบ (Precision@k, BLEU, BERTScore F1, Context Precision/Recall, Faithfulness+Answer
Relevancy จาก Claude judge, Negative Rejection) ผ่าน sanity check + มี provenance และมี "ผลการเทียบ"
ทั้ง 5 แบบข้างบน โดยไม่แตะการรัน ablation เดิม
