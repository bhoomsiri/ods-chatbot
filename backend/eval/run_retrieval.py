"""Phase 1 — retrieval-only ablation (deterministic, no LLM).

For each ``kind=runtime`` config whose eval includes ``retrieval``, run the real
``AnswerQuestion.retrieve`` over the 30-question gold set, score the ranking
against gold pages, and write per-question + aggregate results.

This is READ-ONLY against Qdrant and never calls an answer/judge LLM, so it
cannot mutate the knowledge base or chat history. It DOES load the bge-m3
embedder + reranker locally — run it while the live backend is idle (or in a
one-off container) to avoid GPU contention on a single card.

Usage (from backend/):
    python -m eval.run_retrieval                       # all retrieval configs
    python -m eval.run_retrieval --only baseline E3_topk_10
    python -m eval.run_retrieval --limit 3 --force     # quick smoke
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from app.core.settings import get_settings
from app.domain.entities import ScoredChunk
from app.usecases.answer import RetrievalOutcome
from eval.config import ExperimentConfig, load_configs, select
from eval.datasets import load_eval_items
from eval.datatypes import EvalItem, MetricRow, RetrievalResult, RetrievedContext
from eval.metrics.retrieval import hit_at_k, mrr, ndcg_at_k, recall_at_k
from eval.pipeline import build_retriever

CONFIGS_PATH = Path(__file__).resolve().parent / "configs.yaml"
RUNS_DIR = Path(__file__).resolve().parent / "runs"
K_VALUES: tuple[int, ...] = (1, 3, 5)


def _contexts(scored: Sequence[ScoredChunk]) -> list[RetrievedContext]:
    return [
        RetrievedContext(
            id=sc.chunk.id,
            page=sc.chunk.page,
            source=sc.chunk.source,
            score=round(float(sc.score), 6),
            text=sc.chunk.text,
        )
        for sc in scored
    ]


def score_outcome(
    outcome: RetrievalOutcome, item: EvalItem, latency_ms: float
) -> RetrievalResult:
    """Compute deterministic retrieval metrics for one question."""
    reranked = _contexts(outcome.reranked)
    evidence = _contexts(outcome.evidence)
    gold = item.gold_pages
    ranked_pages: list[int | None] = [c.page for c in reranked]
    evidence_pages: list[int | None] = [c.page for c in evidence]

    metrics: dict[str, float] = {}
    for k in K_VALUES:
        metrics[f"hit@{k}"] = hit_at_k(ranked_pages, gold, k)
        metrics[f"recall@{k}"] = recall_at_k(ranked_pages, gold, k)
        metrics[f"ndcg@{k}"] = ndcg_at_k(ranked_pages, gold, k)
    metrics["mrr"] = mrr(ranked_pages, gold)
    # Evidence-filter view: what actually survives to the LLM.
    metrics["evidence_recall"] = recall_at_k(evidence_pages, gold, len(evidence_pages))
    metrics["n_evidence"] = float(len(evidence))

    # Source-document-level metrics: robust to the hospital .docx files that
    # collapse to a single page (gold page numbers were authored against the
    # original multi-page layout). Skipped for the negative rejection probe,
    # whose correct behavior is to refuse, not to retrieve a source.
    if not item.is_rejection_test and item.gold_sources:
        gold_src = item.gold_sources
        ranked_src: list[str | None] = [c.source for c in reranked]
        for k in K_VALUES:
            metrics[f"src_hit@{k}"] = hit_at_k(ranked_src, gold_src, k)
            metrics[f"src_recall@{k}"] = recall_at_k(ranked_src, gold_src, k)
        metrics["src_mrr"] = mrr(ranked_src, gold_src)

    return RetrievalResult(
        item_id=item.id,
        question=item.question,
        gold_pages=sorted(gold),
        reranked=reranked,
        evidence=evidence,
        refused=not evidence,
        latency_ms=round(latency_ms, 1),
        metrics=metrics,
    )


async def run_config(
    cfg: ExperimentConfig, items: list[EvalItem]
) -> list[RetrievalResult]:
    retriever = build_retriever(cfg, allow_llm=False)
    loop = asyncio.get_event_loop()
    results: list[RetrievalResult] = []
    for item in items:
        start = loop.time()
        outcome = await retriever.retrieve(item.question)
        latency_ms = (loop.time() - start) * 1000.0
        results.append(score_outcome(outcome, item, latency_ms))
    return results


def aggregate(cfg: ExperimentConfig, results: list[RetrievalResult]) -> MetricRow:
    keys = sorted({k for r in results for k in r.metrics})
    agg: dict[str, float] = {}
    for key in keys:
        vals = [r.metrics[key] for r in results if key in r.metrics]
        agg[key] = round(statistics.fmean(vals), 4) if vals else 0.0
    agg["refusal_rate"] = round(sum(1 for r in results if r.refused) / len(results), 4)
    agg["latency_ms_mean"] = round(statistics.fmean([r.latency_ms for r in results]), 1)
    return MetricRow(config=cfg.name, knob=cfg.knob, n=len(results), metrics=agg)


def _results_path(out_dir: Path, name: str) -> Path:
    return out_dir / name / "results.jsonl"


def _write_results(path: Path, results: list[RetrievalResult]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for r in results:
            fh.write(
                json.dumps(
                    {
                        "item_id": r.item_id,
                        "question": r.question,
                        "gold_pages": r.gold_pages,
                        "refused": r.refused,
                        "latency_ms": r.latency_ms,
                        "metrics": r.metrics,
                        "reranked": [
                            {
                                "id": c.id,
                                "page": c.page,
                                "source": c.source,
                                "score": c.score,
                            }
                            for c in r.reranked
                        ],
                        "evidence_pages": [c.page for c in r.evidence],
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )


def _already_done(path: Path, n: int) -> bool:
    if not path.exists():
        return False
    with path.open(encoding="utf-8") as fh:
        return sum(1 for _ in fh) == n


def _print_table(rows: list[MetricRow]) -> None:
    cols = [
        "recall@3",
        "recall@5",
        "mrr",
        "ndcg@5",
        "evidence_recall",
        "refusal_rate",
        "latency_ms_mean",
    ]
    header = f"{'config':<18}{'knob':<22}" + "".join(f"{c:>16}" for c in cols)
    print(header)
    print("-" * len(header))
    for r in rows:
        line = f"{r.config:<18}{r.knob:<22}"
        line += "".join(f"{r.metrics.get(c, 0.0):>16.4f}" for c in cols)
        print(line)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Phase-1 retrieval ablation")
    parser.add_argument("--configs", default=str(CONFIGS_PATH))
    parser.add_argument("--out", default=str(RUNS_DIR))
    parser.add_argument(
        "--only", nargs="*", default=None, help="run only these config names"
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="use only the first N questions (smoke test)",
    )
    parser.add_argument(
        "--force", action="store_true", help="recompute configs even if results exist"
    )
    parser.add_argument(
        "--include-index",
        action="store_true",
        help="also measure kind=index configs (their collections must be built)",
    )
    args = parser.parse_args(argv)

    out_dir = Path(args.out)
    all_configs = load_configs(args.configs)
    configs = select(all_configs, eval_kind="retrieval", kind="runtime")
    if args.include_index:
        configs = configs + select(all_configs, eval_kind="retrieval", kind="index")
    if args.only:
        wanted = set(args.only)
        configs = [c for c in configs if c.name in wanted]
    if not configs:
        print("no matching retrieval configs")
        return 1

    items = load_eval_items()
    if args.limit:
        items = items[: args.limit]

    s = get_settings()
    print(
        f"phase-1 retrieval | {len(configs)} configs x {len(items)} questions "
        f"| use_fakes={s.use_fakes} collection={s.qdrant_collection}"
    )

    rows: list[MetricRow] = []
    for cfg in configs:
        path = _results_path(out_dir, cfg.name)
        if not args.force and _already_done(path, len(items)):
            print(f"  [skip] {cfg.name} (results exist)")
            results = _load_results(path)
        else:
            print(f"  [run ] {cfg.name} ({cfg.knob})")
            results = asyncio.run(run_config(cfg, items))
            _write_results(path, results)
        rows.append(aggregate(cfg, results))

    summary = {
        "phase": "retrieval",
        "generated_at": datetime.now(UTC).isoformat(),
        "collection": s.qdrant_collection,
        "use_fakes": s.use_fakes,
        "k_values": list(K_VALUES),
        "n_questions": len(items),
        "rows": [
            {"config": r.config, "knob": r.knob, "n": r.n, "metrics": r.metrics}
            for r in rows
        ],
    }
    summary_path = out_dir / "_summary_retrieval.json"
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print()
    _print_table(rows)
    print(f"\nsummary -> {summary_path}")
    return 0


def _load_results(path: Path) -> list[RetrievalResult]:
    out: list[RetrievalResult] = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            rec = json.loads(line)
            reranked = [
                RetrievedContext(
                    id=c["id"],
                    page=c["page"],
                    source=c["source"],
                    score=c["score"],
                    text="",
                )
                for c in rec.get("reranked", [])
            ]
            out.append(
                RetrievalResult(
                    item_id=rec["item_id"],
                    question=rec["question"],
                    gold_pages=rec["gold_pages"],
                    reranked=reranked,
                    evidence=[],
                    refused=rec["refused"],
                    latency_ms=rec["latency_ms"],
                    metrics={k: float(v) for k, v in rec["metrics"].items()},
                )
            )
    return out


if __name__ == "__main__":
    raise SystemExit(main())
