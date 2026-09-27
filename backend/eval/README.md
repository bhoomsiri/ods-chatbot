# RAG Ablation & Quality Harness

Proves the pipeline's magic numbers (chunk size, top-k, thresholds, model,
temperature) with data, via **one-factor-at-a-time (OFAT)** ablation on a fixed
30-question gold set. See `benchmark/ABLATION_HARNESS_SPEC.md` for the full
design.

## Why it can't hurt the live system

- **Reuses the real pipeline, no copies.** `pipeline.build_retriever` assembles
  an `AnswerQuestion` from `app.core.providers` and calls
  `AnswerQuestion.retrieve()` — the exact production retrieval logic. There is no
  duplicated pipeline to drift.
- **Read-only.** Retrieval runs only issue `hybrid_search` against Qdrant. They
  never `upsert`, never touch Postgres history, never edit `.env`.
- **No LLM in phase 1.** The retriever is wired with a passthrough analyzer and a
  guard LLM that raises if called, so phase 1 spends zero answer/judge tokens and
  is fully deterministic.
- **Knobs are per-run constructor overrides**, not global settings mutation.

The one real cost: phase 1 loads the bge-m3 embedder + reranker locally. On a
single GPU, run it while the live backend is idle (or in a one-off container) to
avoid VRAM contention — see below.

## Layout

```
eval/
├── datasets/            # byte-identical copies of benchmark/{questions,gold,oos}
├── datatypes.py         # plain dataclasses (EvalItem, RetrievalResult, ...)
├── datasets.py          # loaders (join qset + gold by id)
├── metrics/retrieval.py # hit@k, recall@k, mrr, ndcg — pure & deterministic
├── config.py            # pydantic schema for configs.yaml
├── configs.yaml         # the E1–E9 OFAT matrix (baseline = production values)
├── pipeline.py          # build a retriever from providers + per-run overrides
├── run_retrieval.py     # PHASE 1 entrypoint (retrieval-only, no LLM)
└── runs/                # outputs (gitignored): results.jsonl + _summary_*.json
```

Phase 2 (generation: RAGAS, BERTScore, rejection) and phase 3 (re-index sweeps
for chunk_size/overlap) are **not built yet** — `configs.yaml` already declares
their cells (`eval: [generation]`, `kind: index`) but no runner consumes them.

## Phase 1 — retrieval ablation (this milestone)

Deterministic, no LLM. Scores E3–E7(retrieval) against gold pages.

```bash
# from backend/, with the real services up. Pause the live demo first to free
# the GPU (see "GPU contention").
python -m eval.run_retrieval                      # all retrieval configs, 30 Qs
python -m eval.run_retrieval --only baseline E3_topk_10
python -m eval.run_retrieval --limit 3 --force    # quick smoke
```

Metrics per config (mean over 30 questions): `hit@{1,3,5}`, `recall@{1,3,5}`,
`mrr`, `ndcg@{1,3,5}`, `evidence_recall`, `refusal_rate`, `latency_ms_mean`.
Outputs land in `eval/runs/<config>/results.jsonl` (per question) and
`eval/runs/_summary_retrieval.json`. Re-runs skip configs whose results already
exist (`--force` to recompute).

### GPU contention (important)

The live backend holds bge-m3 + reranker on the GPU. Running the harness in a
second process loads a second copy → on an 8 GB card that risks OOM/CUDA errors.
Safe options:

```bash
# A) pause the live backend, run, restart
docker compose stop backend
docker compose run --rm --no-deps \
  -e ODS_QDRANT_COLLECTION=ods_chunks_v3 \
  backend python -m eval.run_retrieval
docker compose up -d backend

# B) smoke without GPU/services (fake mode): proves wiring, metrics are 0
docker compose run --rm --no-deps -e ODS_USE_FAKES=true \
  backend python -m eval.run_retrieval --limit 3 --force
```

## Tests

Unit tests (fakes, no network, no GPU) live in `backend/tests/unit/`:
`test_eval_metrics.py` (hand-computed metric values), `test_eval_config.py`
(schema), `test_answer_retrieve.py` (retrieve() matches execute(), safety
short-circuits intact). Run with `pytest tests/unit -q`.

## Datasets

`datasets/` is copied from `benchmark/` because the backend container mounts only
`backend/`. They are byte-identical; re-copy if the canonical set changes. Do not
author new questions here.
