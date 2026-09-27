"""KG-compare Phase 2b — run the LightRAG GraphRAG over the same 30 questions.

Mirrors ``run_vector_subset.py`` (same eval set, roles, output schema) but the
answer comes from the knowledge graph instead of the vector store. No judge here
— Phase 3 judges BOTH runs identically. GraphRAG's ``context`` string is kept so
Phase 3 can score faithfulness against what the graph actually retrieved.

Run inside the backend container:
    docker compose exec backend python -m eval.kg_compare.run_graphrag
"""

from __future__ import annotations

import asyncio
import json
from collections import Counter
from collections.abc import Callable
from pathlib import Path
from typing import Any

from app.core.settings import get_settings
from eval.datasets import load_eval_items
from eval.kg_compare.lightrag_retriever import LightRagRetriever, make_rag

HERE = Path(__file__).resolve().parent
CONFIG_PATH = HERE / "subset_config.json"
KG_STORE = HERE.parent / "runs" / "kg_compare" / "kg_store"
OUT_PATH = HERE.parent / "runs" / "kg_compare" / "graphrag" / "results.jsonl"


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
    role_of = _role_fn(conf)
    s = get_settings()
    if not s.gemini_api_key:
        raise RuntimeError("ODS_GEMINI_API_KEY required for GraphRAG answers")

    rag = await make_rag(working_dir=str(KG_STORE), api_key=s.gemini_api_key)
    retriever = LightRagRetriever(rag, mode="mix")

    items = load_eval_items()
    loop = asyncio.get_event_loop()
    records: list[dict[str, Any]] = []
    print(f"graphrag | {len(items)} questions | mode=mix | kg_store={KG_STORE.name}")
    for item in items:
        start = loop.time()
        ga = await retriever.generate(item.question)
        rec: dict[str, Any] = {
            "item_id": item.id,
            "role": role_of(item.id),
            "question": item.question,
            "gold_pages": sorted(item.gold_pages),
            "gold_sources": sorted(item.gold_sources),
            "status": ga.status,
            "refused": ga.refused,
            "answer": ga.answer,
            "n_context_chars": ga.n_context_chars,
            "context": ga.context,
            "error": ga.error,
            "latency_ms": round((loop.time() - start) * 1000.0, 1),
        }
        records.append(rec)
        print(
            f"  q{item.id:>2} [{rec['role']:>13}] {rec['status']:>18} "
            f"refused={rec['refused']} ctx_chars={ga.n_context_chars}"
        )

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUT_PATH.open("w", encoding="utf-8") as fh:
        for r in records:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")

    print("\n=== summary by role (correct = answered for in_subset, refused otherwise) ===")
    for role in ("in_subset", "rejection", "out_of_subset"):
        rs = [r for r in records if r.get("role") == role]
        st = Counter(r.get("status") for r in rs)
        refused = sum(1 for r in rs if r.get("refused"))
        print(
            f"{role:>13}: n={len(rs):>2} answered={st.get('answered', 0):>2} "
            f"refused={refused:>2} statuses={dict(st)}"
        )
    print(f"\nwrote -> {OUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
