# CLAUDE.md — ODS Medical Advisory Chatbot

> ภาษาไทยสั้น ๆ: ไฟล์นี้คือคู่มือหลักให้ Claude Code เข้าใจโปรเจกต์ ทุกการเขียนโค้ดต้องยึด **SOLID + เขียนเทสต์** และต้องตรงกับ **architecture** ด้านล่าง รายละเอียดเชิงปฏิบัติของแต่ละชั้นอยู่ใน `.claude/skills/{frontend,backend,docker}/SKILL.md`

## 1. What we are building

A full-stack **RAG chatbot** that answers questions about **One-Day Surgery (ODS)** for patients and staff at Photharam Hospital. The bot must be **fast, stable, and safe**: it answers **only** from retrieved hospital manuals, **cites the source page**, and **never diagnoses**.

This repo follows a **clone-the-frontend, build-the-backend** strategy: minimal custom frontend code (clone a maintained chat UI), and a clean **FastAPI** backend that owns all RAG logic.

## 2. Target architecture (authoritative)

```
INGESTION (offline):
  Docling (extract + layout/tables) → metadata-aware chunking (tag: category/phase/page, no cross-page)
    → bge-m3 (dense + sparse) → Qdrant (named vectors + payload index)

QUERY (online):
  Frontend (cloned chat UI) → FastAPI
    → query reformulation (Gemini Flash-Lite) + category filter
    → Qdrant hybrid retrieval (dense + sparse, RRF) 
    → bge-reranker-v2-m3 (fp16) → evidence filter (score threshold)
    → Gemini 2.5 Pro (safety system prompt, cite page, low temperature)
    → output guardrail (must contain citation; refuse out-of-scope)
    → stream answer + images from cited pages
```

Each stage sits behind a **port (Protocol)**. Concrete implementations are **adapters**. This is what lets us run the ablation roadmap (swap/add one adapter at a time) without touching use cases. See `RAG_ODS_Full-Tier_Roadmap.md` for the build = eval order.

## 3. Repository layout

```
ods-chatbot/
├── CLAUDE.md
├── .claude/skills/{frontend,backend,docker}/SKILL.md
├── frontend/                 # cloned Next.js chat UI (see frontend skill)
├── backend/
│   ├── app/
│   │   ├── main.py
│   │   ├── core/             # settings, DI container, logging
│   │   ├── domain/           # entities + ports (Protocols) — NO framework imports
│   │   ├── usecases/         # orchestration; depends only on ports
│   │   ├── infrastructure/   # adapters: docling, embeddings, qdrant, reranker, llm, guardrail
│   │   ├── schemas/          # pydantic request/response DTOs
│   │   └── api/routers/      # thin controllers; wire deps via Depends
│   └── tests/{unit,integration,e2e}
├── docker-compose.yml
└── .env.example
```

## 4. Engineering principles (non-negotiable)

- **SOLID, enforced via ports & adapters.** Business logic (`usecases/`) depends on abstractions in `domain/`, never on `infrastructure/`. Wire concretes with FastAPI `Depends`. Adding bge-m3, Qdrant Cloud, a new reranker = a new adapter implementing an existing port. Never edit a use case to add a vendor.
- **Type-safe.** Full type hints; `mypy --strict` on `backend/app`. Pydantic v2 for all I/O boundaries.
- **Tested.** No feature is "done" without tests. Unit tests use fakes for ports (no network). Integration tests run against real Qdrant via docker-compose. Target ≥ 85% coverage on `usecases/` and `infrastructure/`.
- **Fast + stable.** Stream responses (SSE). Keep pre-retrieval cheap (Flash-Lite for reformulation, category via UI). Reranker in fp16. Health checks + graceful degradation (if retrieval empty → safe "ไม่พบข้อมูล").
- **Small, single-responsibility modules.** One adapter = one external concern.

## 5. Critical domain rules (safety)

The generation layer MUST enforce, in priority order:
1. Answer **only** from retrieved context. If evidence filter returns nothing → reply "ไม่พบข้อมูลในคู่มือ กรุณาสอบถามเจ้าหน้าที่".
2. Always **cite the source + page** (e.g. `ODS MIS 2565 หน้า 12`).
3. **Never diagnose** or prescribe. Surface critical instructions first: **NPO (งดน้ำงดอาหาร)** and **wound care (แผลห้ามโดนน้ำ)**.
4. Low temperature for safety-critical answers.
Output guardrail rejects any answer missing a citation or attempting diagnosis.

## 6. Commands

```bash
# Backend
cd backend && uvicorn app.main:app --reload
pytest                      # all tests
pytest tests/unit -q        # fast unit tests
mypy --strict app && ruff check app && ruff format app

# Frontend
cd frontend && pnpm dev
pnpm test                   # vitest
pnpm test:e2e               # playwright

# Full stack
docker compose up --build
```

## 7. Definition of Done

A change is complete when: types pass (`mypy --strict`), lint passes (`ruff`), all tests pass, new logic has unit tests with fakes, any new adapter has an integration test, and the safety rules in §5 still hold. Then update the ablation table in `RAG_ODS_Full-Tier_Roadmap.md` if a RAG stage changed.

## 8. Where to look next

- Frontend work → read `.claude/skills/frontend/SKILL.md`
- Backend / RAG work → read `.claude/skills/backend/SKILL.md`
- Containers / deploy → read `.claude/skills/docker/SKILL.md`
