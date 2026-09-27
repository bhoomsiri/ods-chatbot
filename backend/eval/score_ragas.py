"""Score-only RAGAS metrics with a CLAUDE judge (cross-family, low self-bias).

Reads the saved runs (no re-run) and adds, via the official ``ragas`` library:
- Context Precision / Context Recall on the retrieval configs (contexts = the
  evidence chunk texts, fetched from Qdrant by the ids saved in results.jsonl).
- Re-judged Faithfulness / Answer Relevancy on the generated answers, reported
  next to the original Gemini-Flash judge scores (comparison #4).

Judge = Anthropic Claude (answer model is Gemini) so the grader is a different
family — asserted at startup (guarantee G). Embeddings = bge-m3 on CPU (no GPU
contention with the live demo). Needs ANTHROPIC_API_KEY in the environment.

Only configs on the live ``ods_chunks_v3`` can fetch contexts; E1/E2 collections
were deleted -> their context metrics are N/A. Gen configs did not save their
context ids, so Faithfulness re-judge uses the matching retrieval config's
evidence as a documented proxy (Answer Relevancy needs no contexts).

Usage (one-off container with ragas + langchain-anthropic installed):
    python -m eval.score_ragas --only baseline --limit 3   # validate
    python -m eval.score_ragas                              # full
"""

from __future__ import annotations

import argparse
import json
import math
import os
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.core.settings import get_settings
from eval.config import ExperimentConfig, load_configs
from eval.datasets import load_eval_items

RUNS_DIR = Path(__file__).resolve().parent / "runs"
CLAUDE_JUDGE_MODEL = "claude-sonnet-4-6"
ANSWER_MODEL_FAMILY = "gemini"
LIVE_COLLECTION = "ods_chunks_v3"

# Each gen config's contexts (not saved) are proxied by the matching retrieval
# config's evidence (same knobs bar reformulation). E8/E9 vary only generation,
# so they reuse baseline retrieval. Documented approximation for Faithfulness;
# Answer Relevancy needs no contexts.
RETRIEVAL_FOR_GEN = {
    "gen_baseline": "baseline",
    "gen_E5_rrtopk_5": "E5_rrtopk_5",
    "gen_E5_rrtopk_10": "E5_rrtopk_10",
    "gen_E7_qt_off": "E7_qt_off",
    "gen_E8_model_pro": "baseline",
    "gen_E8_model_flash_lite": "baseline",
    "gen_E9_temp_0.0": "baseline",
    "gen_E9_temp_0.3": "baseline",
    "gen_E9_temp_0.5": "baseline",
}


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as fh:
        return [json.loads(line) for line in fh]


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def assert_cross_family(judge_model: str) -> None:
    """Guarantee G: the judge must not be the same family as the answer model."""
    j = judge_model.lower()
    if "claude" not in j:
        raise ValueError(f"judge must be Claude, got {judge_model!r}")
    if ANSWER_MODEL_FAMILY in j:
        raise ValueError("judge and answer model share a family (self-bias)")


def evidence_ids(rec: dict[str, Any], threshold: float) -> list[str]:
    """Reconstruct the evidence chunk ids fed to the LLM: reranked entries whose
    score cleared this config's evidence-filter threshold."""
    return [
        str(c["id"])
        for c in rec.get("reranked", [])
        if float(c.get("score", 0.0)) >= threshold
    ]


class QdrantContextFetcher:
    """Fetch chunk text by *logical* chunk id from the live collection.

    Qdrant point ids are the store's blake2b hash of the chunk id (payload keeps
    the original ``chunk_id`` + ``text``), so we derive the point id with the same
    function the store uses — reusing it, not re-deriving the scheme.
    """

    def __init__(self, collection: str) -> None:
        from qdrant_client import QdrantClient

        s = get_settings()
        self._client = QdrantClient(url=s.qdrant_url, api_key=s.qdrant_api_key)
        self._collection = collection
        self._cache: dict[str, str] = {}

    def texts(self, ids: Sequence[str]) -> list[str]:
        from app.infrastructure.qdrant_store import _point_id

        missing = [i for i in ids if i not in self._cache]
        if missing:
            points = self._client.retrieve(
                collection_name=self._collection,
                ids=[_point_id(i) for i in missing],
                with_payload=True,
            )
            for p in points:
                payload = p.payload or {}
                cid = str(payload.get("chunk_id", p.id))
                self._cache[cid] = str(payload.get("text", ""))
        return [self._cache[i] for i in ids if self._cache.get(i)]


def build_judge() -> Any:
    """LangchainLLMWrapper around ChatAnthropic (temperature 0)."""
    from langchain_anthropic import ChatAnthropic
    from ragas.llms import LangchainLLMWrapper

    assert_cross_family(CLAUDE_JUDGE_MODEL)
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise RuntimeError("ANTHROPIC_API_KEY not set")
    llm = ChatAnthropic(
        model_name=CLAUDE_JUDGE_MODEL, temperature=0.0, timeout=120, stop=None
    )
    return LangchainLLMWrapper(llm)


def build_embeddings() -> Any:
    """bge-m3 on CPU wrapped for ragas (no GPU contention)."""
    from langchain_core.embeddings import Embeddings
    from ragas.embeddings import LangchainEmbeddingsWrapper

    class _BGEm3CPU(Embeddings):  # type: ignore[misc]
        def __init__(self) -> None:
            from FlagEmbedding import BGEM3FlagModel

            self._m = BGEM3FlagModel("BAAI/bge-m3", use_fp16=False, devices="cpu")

        def embed_documents(self, texts: list[str]) -> list[list[float]]:
            out = self._m.encode(texts, return_dense=True, return_sparse=False)
            return [list(map(float, v)) for v in out["dense_vecs"]]

        def embed_query(self, text: str) -> list[float]:
            return self.embed_documents([text])[0]

    return LangchainEmbeddingsWrapper(_BGEm3CPU())


def _config_by_name(
    configs: list[ExperimentConfig], name: str
) -> ExperimentConfig | None:
    return next((c for c in configs if c.name == name), None)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Score-only RAGAS (Claude judge)")
    parser.add_argument("--out", default=str(RUNS_DIR))
    parser.add_argument("--only", nargs="*", default=None)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument(
        "--skip-context",
        action="store_true",
        help="don't recompute Context P/R; keep the values already in the summary",
    )
    parser.add_argument(
        "--gen",
        nargs="*",
        default=None,
        help="only re-judge these gen configs (economical); default = all",
    )
    args = parser.parse_args(argv)
    out_dir = Path(args.out)

    from ragas import EvaluationDataset, evaluate
    from ragas.metrics import (
        Faithfulness,
        LLMContextPrecisionWithReference,
        LLMContextRecall,
        ResponseRelevancy,
    )

    judge = build_judge()
    embeddings = build_embeddings()
    items = {it.id: it for it in load_eval_items()}
    configs = load_configs(RUNS_DIR.parent / "configs.yaml")
    fetcher = QdrantContextFetcher(LIVE_COLLECTION)

    provenance = {
        "generated_at": datetime.now(UTC).isoformat(),
        "judge_model": CLAUDE_JUDGE_MODEL,
        "answer_model_family": ANSWER_MODEL_FAMILY,
        "embeddings": "bge-m3 (cpu)",
        "collection": LIVE_COLLECTION,
    }
    print("=== RAGAS provenance ===")
    print(json.dumps(provenance, ensure_ascii=False, indent=2))

    # ---- Context Precision / Recall on retrieval configs (v3 only) ----
    # Reuse already-computed context metrics (expensive) unless recomputing.
    existing = _load(out_dir / "_summary_ragas.json")
    ctx_rows: dict[str, dict[str, float]] = (
        existing.get("context_metrics", {}) if args.skip_context else {}
    )
    retr_dirs = (
        []
        if args.skip_context
        else [
            d
            for d in sorted(out_dir.iterdir())
            if (d / "results.jsonl").exists()
            and not d.name.startswith("gen_")
            and not d.name.startswith("E1_")
            and not d.name.startswith("E2_")
        ]
    )
    if args.only:
        retr_dirs = [d for d in retr_dirs if d.name in set(args.only)]

    for d in retr_dirs:
        cfg = _config_by_name(configs, d.name)
        thr = cfg.query.score_threshold if cfg else 0.3
        samples = []
        for rec in _read_jsonl(d / "results.jsonl"):
            item = items.get(int(rec["item_id"]))
            if item is None or item.is_rejection_test or not item.gold_answer:
                continue
            ctx = fetcher.texts(evidence_ids(rec, thr))
            if not ctx:
                continue
            samples.append(
                {
                    "user_input": item.question,
                    "retrieved_contexts": ctx,
                    "reference": item.gold_answer,
                }
            )
        if args.limit:
            samples = samples[: args.limit]
        if not samples:
            continue
        ds = EvaluationDataset.from_list(samples)
        result = evaluate(
            ds,
            metrics=[LLMContextPrecisionWithReference(), LLMContextRecall()],
            llm=judge,
            embeddings=embeddings,
        )
        df = result.to_pandas()
        prec_col = "llm_context_precision_with_reference"
        ctx_rows[d.name] = {
            "n": float(len(samples)),
            "context_precision": round(float(df[prec_col].mean()), 4),
            "context_recall": round(float(df["context_recall"].mean()), 4),
        }
        print(f"  [ctx] {d.name}: {ctx_rows[d.name]}")

    # ---- Re-judge Faithfulness / Answer Relevancy on gen configs (Claude) ----
    # Build the proxy context map once per referenced retrieval config.
    evidence_cache: dict[str, dict[int, list[str]]] = {}

    def evidence_map(retr_name: str) -> dict[int, list[str]]:
        if retr_name in evidence_cache:
            return evidence_cache[retr_name]
        cfg = _config_by_name(configs, retr_name)
        thr = cfg.query.score_threshold if cfg else 0.3
        m: dict[int, list[str]] = {}
        rpath = out_dir / retr_name / "results.jsonl"
        if rpath.exists():
            for rec in _read_jsonl(rpath):
                m[int(rec["item_id"])] = fetcher.texts(evidence_ids(rec, thr))
        evidence_cache[retr_name] = m
        return m

    # Preserve any re-judge results already saved (so a targeted, economical
    # re-run of a few gen configs merges with, not clobbers, prior work).
    regen_rows: dict[str, dict[str, Any]] = (
        existing.get("regen_judge", {}) if args.skip_context else {}
    )
    judge_pairs: list[dict[str, Any]] = (
        existing.get("judge_pairs", []) if args.skip_context else []
    )
    gen_filter = args.gen or args.only
    gen_dirs = sorted(out_dir.glob("gen_*"))
    if gen_filter:
        gen_dirs = [d for d in gen_dirs if d.name in set(gen_filter)]
    # Drop prior rows/pairs for the configs we are about to recompute.
    recompute = {d.name for d in gen_dirs}
    regen_rows = {k: v for k, v in regen_rows.items() if k not in recompute}
    judge_pairs = [p for p in judge_pairs if p.get("config") not in recompute]
    for d in gen_dirs:
        if not (d / "results.jsonl").exists():
            continue
        ctx_by_item = evidence_map(RETRIEVAL_FOR_GEN.get(d.name, "baseline"))
        samples = []
        flash: list[dict[str, Any]] = []
        for rec in _read_jsonl(d / "results.jsonl"):
            if rec.get("status") != "answered":
                continue
            item = items.get(int(rec["item_id"]))
            if item is None or not item.gold_answer:
                continue
            ctx = ctx_by_item.get(item.id) or [item.gold_answer]
            samples.append(
                {
                    "user_input": item.question,
                    "response": str(rec.get("answer", "")),
                    "retrieved_contexts": ctx,
                    "reference": item.gold_answer,
                }
            )
            flash.append(
                {
                    "item_id": item.id,
                    "flash_faithfulness": rec.get("faithfulness"),
                    "flash_answer_relevancy": rec.get("answer_relevancy"),
                }
            )
        if args.limit:
            samples, flash = samples[: args.limit], flash[: args.limit]
        if not samples:
            continue
        ds = EvaluationDataset.from_list(samples)
        result = evaluate(
            ds,
            metrics=[Faithfulness(), ResponseRelevancy()],
            llm=judge,
            embeddings=embeddings,
        )
        df = result.to_pandas()
        cf = [float(x) for x in df["faithfulness"]]
        cr = [float(x) for x in df["answer_relevancy"]]

        def _mean(xs: list[float]) -> float | None:
            valid = [x for x in xs if not math.isnan(x)]
            return round(sum(valid) / len(valid), 4) if valid else None

        cf_valid = [x for x in cf if not math.isnan(x)]
        regen_rows[d.name] = {
            "n": float(len(samples)),
            "n_faith_valid": float(len(cf_valid)),
            "claude_faithfulness": _mean(cf),
            "claude_answer_relevancy": _mean(cr),
        }
        for fl, c_f, c_r in zip(flash, cf, cr, strict=True):
            judge_pairs.append(
                {
                    **fl,
                    "config": d.name,
                    "claude_faithfulness": None if math.isnan(c_f) else round(c_f, 4),
                    "claude_answer_relevancy": None if math.isnan(c_r) else round(c_r, 4),
                }
            )
        print(f"  [regen] {d.name}: {regen_rows[d.name]}")

    summary = {
        "phase": "ragas",
        "provenance": provenance,
        "context_metrics": ctx_rows,
        "regen_judge": regen_rows,
        "judge_pairs": judge_pairs,
    }
    path = out_dir / "_summary_ragas.json"
    path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nsummary -> {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
