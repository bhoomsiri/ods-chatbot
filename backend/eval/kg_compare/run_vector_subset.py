"""KG-compare Phase 1 — hybrid vector RAG restricted to the 3-doc subset.

Runs the production online pipeline (retrieve → rerank → evidence@0.3 → Gemini →
guardrail) but with retrieval constrained to the subset ``source`` values, over
all 30 gold questions. Records the answer, evidence and role
(in_subset / out_of_subset / rejection) for the Phase 3 scorer. No judge here —
Phase 3 judges BOTH RAGs identically (fairness gate E).

Isolation: read-only vs Qdrant (query + payload filter only). Answers via the
same Gemini model production uses.

Run inside the backend container (it has the bge-m3 embedder, reranker + GPU):
    docker compose exec backend python -m eval.kg_compare.run_vector_subset
"""

from __future__ import annotations

import asyncio
import json
from collections import Counter
from collections.abc import Callable
from pathlib import Path
from typing import Any

from app.core.settings import get_settings
from eval.config import ExperimentConfig
from eval.datasets import load_eval_items
from eval.kg_compare.subset_store import SubsetVectorStore
from eval.pipeline import build_retriever

HERE = Path(__file__).resolve().parent
CONFIG_PATH = HERE / "subset_config.json"
OUT_PATH = HERE.parent / "runs" / "kg_compare" / "vector_subset" / "results.jsonl"


def _role_fn(conf: dict[str, Any]) -> Callable[[int], str]:
    es = conf["eval_set"]
    in_q = set(es["in_subset_quality"]["gold_question_ids"])
    rej = {es["in_subset_quality"]["rejection_probe_id"]}
    out = set(es["out_of_subset_rejection"]["gold_question_ids"])

    def role(qid: int) -> str:
        if qid in rej:
            return "rejection"
        if qid in in_q:
            return "in_subset"
        if qid in out:
            return "out_of_subset"
        return "unknown"

    return role


async def main() -> int:
    conf = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    sources = conf["qdrant"]["subset_sources"]
    collection = conf["qdrant"]["collection"]
    role_of = _role_fn(conf)

    s = get_settings()
    # Production baseline knobs (top_k20 / cand20 / rerank8 / thr0.3 /
    # reformulate / gemini-2.5-flash / temp0.1) come from the config defaults.
    cfg = ExperimentConfig(name="vector_subset", collection=collection)
    retriever = build_retriever(cfg, allow_llm=True)
    # Constrain retrieval to the subset. Reassigning the store keeps the exact
    # production analyzer / reranker / LLM / guardrail wiring; only the candidate
    # pool is filtered to the subset documents (isolation: query + filter only).
    retriever._store = SubsetVectorStore(  # noqa: SLF001 - deliberate injection
        sources=sources,
        url=s.qdrant_url,
        api_key=s.qdrant_api_key,
        collection=collection,
        dense_size=s.embedding_dim,
    )

    items = load_eval_items()
    loop = asyncio.get_event_loop()
    records: list[dict[str, Any]] = []
    print(
        f"vector_subset | {len(items)} questions | collection={collection} | "
        f"subset_sources={len(sources)}"
    )
    for item in items:
        start = loop.time()
        try:
            gen = await retriever.generate(item.question)
            rec: dict[str, Any] = {
                "item_id": item.id,
                "role": role_of(item.id),
                "question": item.question,
                "gold_pages": sorted(item.gold_pages),
                "gold_sources": sorted(item.gold_sources),
                "status": gen.status,
                "refused": gen.refused,
                "answer": gen.answer,
                "guardrail_allowed": gen.guardrail_allowed,
                "n_evidence": len(gen.evidence),
                "evidence": [
                    {
                        "source": c.chunk.source,
                        "page": c.chunk.page,
                        "score": round(float(c.score), 6),
                        "text": c.chunk.text,
                    }
                    for c in gen.evidence
                ],
            }
        except Exception as exc:  # noqa: BLE001 - record, don't abort the sweep
            rec = {
                "item_id": item.id,
                "role": role_of(item.id),
                "status": "error",
                "error": str(exc)[:200],
            }
        rec["latency_ms"] = round((loop.time() - start) * 1000.0, 1)
        records.append(rec)
        print(
            f"  q{item.id:>2} [{rec.get('role', '?'):>13}] "
            f"{rec.get('status', '?'):>18} refused={rec.get('refused')} "
            f"ev={rec.get('n_evidence', '-')}"
        )

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUT_PATH.open("w", encoding="utf-8") as fh:
        for r in records:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")

    # Correct behavior: in_subset -> answered; out_of_subset & rejection -> refused.
    print("\n=== summary by role (correct = answered for in_subset, refused otherwise) ===")
    for role in ("in_subset", "rejection", "out_of_subset"):
        rs = [r for r in records if r.get("role") == role]
        st = Counter(r.get("status") for r in rs)
        answered = st.get("answered", 0)
        refused = sum(1 for r in rs if r.get("refused"))
        print(
            f"{role:>13}: n={len(rs):>2} answered={answered:>2} refused={refused:>2} "
            f"statuses={dict(st)}"
        )
    print(f"\nwrote -> {OUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
