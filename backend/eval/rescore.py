"""Re-score existing retrieval runs at the SOURCE-document level — no re-run.

Phase-1 ``results.jsonl`` already stores each retrieved chunk's ``source``, so we
can compute source-level recall offline (free, no GPU). This exposes the true
retrieval quality that page-level recall understates: the hospital .docx files
collapse to a single page, but gold page numbers were authored against the
original multi-page layout, so a correct retrieval is scored as a page "miss".

Usage (from backend/):
    python -m eval.rescore                 # all runs under eval/runs/
    python -m eval.rescore --out eval/runs
"""

from __future__ import annotations

import argparse
import json
import statistics
from collections.abc import Sequence
from pathlib import Path

from eval.datasets import load_eval_items
from eval.datatypes import EvalItem
from eval.metrics.retrieval import hit_at_k, mrr, recall_at_k

RUNS_DIR = Path(__file__).resolve().parent / "runs"
K_VALUES: tuple[int, ...] = (1, 3, 5)


def _rescore_config(path: Path, items: dict[int, EvalItem]) -> dict[str, float]:
    page_recall5: list[float] = []
    src_hit5: list[float] = []
    src_recall5: list[float] = []
    src_mrr: list[float] = []
    n_scored = 0
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            rec = json.loads(line)
            item = items.get(int(rec["item_id"]))
            if item is None or item.is_rejection_test or not item.gold_sources:
                continue
            n_scored += 1
            page_recall5.append(float(rec["metrics"].get("recall@5", 0.0)))
            ranked_src: list[str | None] = [c["source"] for c in rec.get("reranked", [])]
            src_hit5.append(hit_at_k(ranked_src, item.gold_sources, 5))
            src_recall5.append(recall_at_k(ranked_src, item.gold_sources, 5))
            src_mrr.append(mrr(ranked_src, item.gold_sources))

    def m(xs: list[float]) -> float:
        return round(statistics.fmean(xs), 4) if xs else 0.0

    return {
        "n_scored": float(n_scored),
        "page_recall@5": m(page_recall5),
        "src_hit@5": m(src_hit5),
        "src_recall@5": m(src_recall5),
        "src_mrr": m(src_mrr),
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Source-level re-score (offline)")
    parser.add_argument("--out", default=str(RUNS_DIR))
    args = parser.parse_args(argv)

    out_dir = Path(args.out)
    items = {it.id: it for it in load_eval_items()}
    config_dirs = sorted(p for p in out_dir.iterdir() if (p / "results.jsonl").exists())
    if not config_dirs:
        print(f"no results.jsonl under {out_dir}")
        return 1

    cols = ["n_scored", "page_recall@5", "src_hit@5", "src_recall@5", "src_mrr"]
    header = f"{'config':<18}" + "".join(f"{c:>16}" for c in cols)
    print(header)
    print("-" * len(header))
    rows: dict[str, dict[str, float]] = {}
    for d in config_dirs:
        agg = _rescore_config(d / "results.jsonl", items)
        rows[d.name] = agg
        line = f"{d.name:<18}" + "".join(f"{agg[c]:>16.4f}" for c in cols)
        print(line)

    summary_path = out_dir / "_summary_source.json"
    summary_path.write_text(
        json.dumps(
            {"k_values": list(K_VALUES), "rows": rows}, ensure_ascii=False, indent=2
        ),
        encoding="utf-8",
    )
    print(f"\nsummary -> {summary_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
