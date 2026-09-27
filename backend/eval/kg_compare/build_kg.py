"""KG-compare Phase 2 — build the LightRAG graph over the 3-doc subset.

Records the cost axis (index seconds, LLM extraction calls/tokens, node/edge
counts) and dumps an entity/relation sample for the Thai quality gate (§6.5-C).
Stops after building — inspect ``kg_graph_sample.json`` before running queries.

Run inside the backend container (bge-m3 + GPU + Gemini key):
    docker compose exec backend python -m eval.kg_compare.build_kg          # build
    docker compose exec backend python -m eval.kg_compare.build_kg --force  # rebuild
"""

from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import time
from pathlib import Path
from typing import Any

from app.core.settings import get_settings
from eval.kg_compare.kg_index_builder import graph_stats, load_subset_docs
from eval.kg_compare.kg_llm import make_bge_embedding_func, make_gemini_llm_func

HERE = Path(__file__).resolve().parent
CONFIG_PATH = HERE / "subset_config.json"
RUNS = HERE.parent / "runs" / "kg_compare"
KG_STORE = RUNS / "kg_store"
OUT = RUNS / "graphrag"
CHARS_PER_TOKEN = 3.0


def _cost_from_cache(working_dir: Path) -> dict[str, float]:
    """Sum LightRAG's persisted LLM cache — complete extraction cost, crash-proof.

    Walks ``kv_store_llm_response_cache.json`` counting cached responses and their
    char totals (prompt + return where present). Robust to schema nesting.
    """
    cache = working_dir / "kv_store_llm_response_cache.json"
    if not cache.exists():
        return {"llm_calls": 0}
    data = json.loads(cache.read_text(encoding="utf-8"))
    calls = 0
    prompt_chars = 0
    completion_chars = 0

    def walk(obj: Any) -> None:
        nonlocal calls, prompt_chars, completion_chars
        if isinstance(obj, dict):
            if "return" in obj and isinstance(obj.get("return"), str):
                calls += 1
                completion_chars += len(obj["return"])
                for k in ("original_prompt", "prompt"):
                    if isinstance(obj.get(k), str):
                        prompt_chars += len(obj[k])
                        break
            else:
                for v in obj.values():
                    walk(v)
        elif isinstance(obj, list):
            for v in obj:
                walk(v)

    walk(data)
    return {
        "llm_calls": calls,
        "prompt_chars": prompt_chars,
        "completion_chars": completion_chars,
        "prompt_tokens_est": round(prompt_chars / CHARS_PER_TOKEN, 1),
        "completion_tokens_est": round(completion_chars / CHARS_PER_TOKEN, 1),
        "total_tokens_est": round((prompt_chars + completion_chars) / CHARS_PER_TOKEN, 1),
    }


async def build(force: bool) -> int:
    conf = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    sources = conf["qdrant"]["subset_sources"]
    collection = conf["qdrant"]["collection"]
    s = get_settings()

    if force and KG_STORE.exists():
        shutil.rmtree(KG_STORE)
    KG_STORE.mkdir(parents=True, exist_ok=True)
    OUT.mkdir(parents=True, exist_ok=True)

    print(f"[1/4] reconstructing subset corpus from {collection} ({len(sources)} docs)")
    docs = load_subset_docs(
        url=s.qdrant_url, api_key=s.qdrant_api_key, collection=collection, sources=sources
    )
    for d in docs:
        print(f"      - {d.source[:40]:<42} chunks={d.n_chunks:>4} chars={d.n_chars:>7}")
    total_chars = sum(d.n_chars for d in docs)

    print("[2/4] initializing LightRAG (gemini-2.5-flash + bge-m3)")
    from lightrag import LightRAG
    from lightrag.kg.shared_storage import initialize_pipeline_status
    from lightrag.utils import EmbeddingFunc

    if not s.gemini_api_key:
        raise RuntimeError("ODS_GEMINI_API_KEY required to build the KG")
    llm_func, meter = make_gemini_llm_func(
        api_key=s.gemini_api_key, model="gemini-2.5-flash", temperature=0.1
    )
    embed_func, _ = make_bge_embedding_func(use_fp16=True)

    rag = LightRAG(
        working_dir=str(KG_STORE),
        llm_model_func=llm_func,
        llm_model_name="gemini-2.5-flash",
        embedding_func=EmbeddingFunc(
            embedding_dim=1024, max_token_size=8192, func=embed_func
        ),
        # Extract entities/relations in Thai (default prompt emits English, which
        # for a Thai corpus loses nuance and hurts Thai-query matching). Giving
        # LightRAG the language-appropriate config is the fair choice (§6.5).
        addon_params={"language": "Thai"},
        # Memory ceiling: the default fan-out (parallel docs + 8 embed workers)
        # OOM-crashed the WSL VM during the merge of the largest doc. Process one
        # doc at a time with a small worker pool — slower, but it fits in RAM.
        max_parallel_insert=1,
        embedding_func_max_async=2,
        embedding_batch_num=8,
        llm_model_max_async=4,
    )
    await rag.initialize_storages()
    await initialize_pipeline_status()

    # ainsert is idempotent (LightRAG tracks doc_status by id + content hash):
    # completed docs are skipped and pending/failed ones retried, reusing the
    # persisted LLM extraction cache. So this doubles as a crash-resume — never
    # guard it out, or a partially-built graph never finishes.
    print(f"[3/4] inserting/resuming {len(docs)} docs (~{total_chars} chars)")
    t0 = time.time()
    await rag.ainsert(
        [d.text for d in docs],
        ids=[f"subset::{i}" for i in range(len(docs))],
        file_paths=[d.source for d in docs],
    )
    index_seconds = round(time.time() - t0, 1)
    print(f"      insert returned in {index_seconds}s (this run only)")

    print("[4/4] collecting graph stats + Thai quality-gate sample")
    gstats = graph_stats(KG_STORE)

    stats: dict[str, Any] = {
        "collection": collection,
        "subset_sources": sources,
        "n_docs": len(docs),
        "n_source_chunks": sum(d.n_chunks for d in docs),
        "total_chars_inserted": total_chars,
        "index_seconds_this_run": index_seconds,
        # Robust across a crash-resume: the persisted extraction cache holds
        # every LLM call ever made for this build, so this is the COMPLETE cost
        # even though the in-process meter (below) only counts this run.
        "llm_extraction_cost_from_cache": _cost_from_cache(KG_STORE),
        "llm_extraction_cost_this_run": meter.summary(),
        "graph": {k: v for k, v in gstats.items() if not k.startswith("sample_")},
        "answer_model": "gemini-2.5-flash",
        "embeddings": "bge-m3 (dense, 1024)",
        "note": "Build survived a Docker-engine crash mid-extraction; LLM calls "
        "were cached so cost_from_cache is complete, but index_seconds_this_run "
        "reflects only the final resume run, not total wall-clock.",
    }
    (OUT / "kg_build_stats.json").write_text(
        json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (OUT / "kg_graph_sample.json").write_text(
        json.dumps(
            {
                "n_nodes": gstats["n_nodes"],
                "n_edges": gstats["n_edges"],
                "sample_entities": gstats.get("sample_entities", []),
                "sample_relations": gstats.get("sample_relations", []),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    print("\n=== KG build summary ===")
    print(f"nodes={gstats['n_nodes']} edges={gstats['n_edges']} "
          f"index_seconds={index_seconds}")
    print(f"LLM extraction: {meter.summary()}")
    print(f"stats  -> {OUT / 'kg_build_stats.json'}")
    print(f"sample -> {OUT / 'kg_graph_sample.json'}  (inspect for Thai gate §6.5-C)")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="KG-compare Phase 2 — build LightRAG graph")
    ap.add_argument("--force", action="store_true", help="wipe kg_store and rebuild")
    args = ap.parse_args()
    return asyncio.run(build(args.force))


if __name__ == "__main__":
    raise SystemExit(main())
