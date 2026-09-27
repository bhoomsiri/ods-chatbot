"""Score-only add-metrics — computes new metrics OVER the saved ablation runs.

Reads ``runs/*/results.jsonl`` (no re-ingest / re-retrieve / re-generate) and adds:
- Precision@k (page + source) for every retrieval config — deterministic.
- BLEU (sacrebleu + pythainlp) and BERTScore F1 (bert-score) for every gen config.

Runs the golden sanity checks (identical -> BLEU 100 / BERTScore ~1; unrelated ->
BLEU ~0 / BERTScore floor) before trusting the batch, records library/model
provenance, and dumps a per-metric spot-check. The Claude/RAGAS metrics (Context
P/R + re-judge) live in ``score_ragas.py`` and need ANTHROPIC_API_KEY.

Usage (in a one-off CPU container with the scoring deps):
    python -m eval.score_metrics
"""

from __future__ import annotations

import argparse
import json
import statistics
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from eval.datasets import load_eval_items
from eval.metrics.retrieval import precision_at_k
from eval.metrics.text_metrics import (
    bertscore_f1,
    corpus_bleu,
    pin_versions,
    sentence_bleu,
)

RUNS_DIR = Path(__file__).resolve().parent / "runs"
K_VALUES: tuple[int, ...] = (1, 3, 5)
BERTSCORE_MODEL = "xlm-roberta-large"


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as fh:
        return [json.loads(line) for line in fh]


def provenance() -> dict[str, object]:
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "libraries": pin_versions(),
        "bertscore_model": BERTSCORE_MODEL,
        "bertscore_device": "cpu",
        "flash_judge_model": "gemini-2.5-flash (from prior generation run)",
    }


def sanity_check(sample_gold: str) -> dict[str, float]:
    """C: identical -> BLEU 100 / BERTScore ~1; unrelated -> BLEU ~0 / floor."""
    unrelated = "ราคาหุ้นกลุ่มโรงพยาบาลวันนี้ปรับตัวสูงขึ้นเล็กน้อย"
    bleu_id = corpus_bleu([sample_gold], [sample_gold]).bleu
    bleu_un = corpus_bleu([unrelated], [sample_gold]).bleu
    f_id, f_un = bertscore_f1(
        [sample_gold, unrelated], [sample_gold, sample_gold], model_type=BERTSCORE_MODEL
    )
    if bleu_id < 99.9:
        raise ValueError(f"sanity: identical BLEU {bleu_id} != 100")
    if bleu_un >= bleu_id:
        raise ValueError("sanity: unrelated BLEU not below identical")
    if not (f_id > 0.9 and f_id > f_un):
        raise ValueError(f"sanity: BERTScore identical={f_id} unrelated={f_un}")
    return {
        "bleu_identical": round(bleu_id, 2),
        "bleu_unrelated": round(bleu_un, 2),
        "bertscore_identical": round(f_id, 4),
        "bertscore_unrelated_floor": round(f_un, 4),
    }


def score_retrieval(out_dir: Path) -> dict[str, dict[str, float]]:
    """Precision@k (page + source) per retrieval config."""
    items = {it.id: it for it in load_eval_items()}
    rows: dict[str, dict[str, float]] = {}
    for d in sorted(out_dir.iterdir()):
        results = d / "results.jsonl"
        if d.name.startswith("gen_") or not results.exists():
            continue
        recs = _read_jsonl(results)
        per_k_page: dict[int, list[float]] = {k: [] for k in K_VALUES}
        per_k_src: dict[int, list[float]] = {k: [] for k in K_VALUES}
        for rec in recs:
            item = items.get(int(rec["item_id"]))
            if item is None or item.is_rejection_test:
                continue
            reranked = rec.get("reranked", [])
            pages: list[int | None] = [c.get("page") for c in reranked]
            srcs: list[str | None] = [c.get("source") for c in reranked]
            for k in K_VALUES:
                per_k_page[k].append(precision_at_k(pages, item.gold_pages, k))
                if item.gold_sources:
                    per_k_src[k].append(precision_at_k(srcs, item.gold_sources, k))
        agg: dict[str, float] = {}
        for k in K_VALUES:
            agg[f"precision_page@{k}"] = round(statistics.fmean(per_k_page[k]), 4)
            if per_k_src[k]:
                agg[f"precision_src@{k}"] = round(statistics.fmean(per_k_src[k]), 4)
        rows[d.name] = agg
    return rows


def score_generation(
    out_dir: Path,
) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    """BLEU + BERTScore F1 per gen config. Returns (agg, per-item spot rows)."""
    items = {it.id: it for it in load_eval_items()}
    rows: dict[str, dict[str, Any]] = {}
    spot: list[dict[str, Any]] = []
    for d in sorted(out_dir.glob("gen_*")):
        results = d / "results.jsonl"
        if not results.exists():
            continue
        recs = _read_jsonl(results)
        cands: list[str] = []
        refs: list[str] = []
        ids: list[int] = []
        for rec in recs:
            if rec.get("status") != "answered":
                continue
            item = items.get(int(rec["item_id"]))
            if item is None or not item.gold_answer:
                continue
            cands.append(str(rec.get("answer", "")))
            refs.append(item.gold_answer)
            ids.append(item.id)
        if not cands:
            continue
        bleu = corpus_bleu(cands, refs)
        f1s = bertscore_f1(cands, refs, model_type=BERTSCORE_MODEL)
        mean_f1 = round(statistics.fmean(f1s), 4)
        rows[d.name] = {
            "n": float(len(cands)),
            "bleu": round(bleu.bleu, 2),
            "bleu_1": round(bleu.precisions[0], 2),
            "bleu_2": round(bleu.precisions[1], 2),
            "bleu_3": round(bleu.precisions[2], 2),
            "bleu_4": round(bleu.precisions[3], 2),
            # mean per-config BERTScore F1; both key names for downstream tools
            "bertscore_f1": mean_f1,
            "bertscore_f1_mean": mean_f1,
            # per-item F1 kept for traceability (item_id -> F1)
            "bertscore_f1_by_item": {
                str(i): round(f, 4) for i, f in zip(ids, f1s, strict=True)
            },
        }
        # F: spot-check 3 items for the baseline config
        if d.name == "gen_baseline":
            for i in range(min(3, len(cands))):
                spot.append(
                    {
                        "item_id": ids[i],
                        "sentence_bleu": round(sentence_bleu(cands[i], refs[i]), 2),
                        "bertscore_f1": round(f1s[i], 4),
                        "answer": cands[i][:160],
                        "gold_answer": refs[i][:160],
                    }
                )
    return rows, spot


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Score-only add-metrics")
    parser.add_argument("--out", default=str(RUNS_DIR))
    args = parser.parse_args(argv)
    out_dir = Path(args.out)

    items = load_eval_items()
    sample_gold = next(it.gold_answer for it in items if it.gold_answer)

    print("=== provenance ===")
    prov = provenance()
    print(json.dumps(prov, ensure_ascii=False, indent=2))

    print("\n=== sanity (C) ===")
    sanity = sanity_check(sample_gold)
    print(json.dumps(sanity, ensure_ascii=False))

    print("\n=== Precision@k (retrieval configs) ===")
    retr = score_retrieval(out_dir)
    for name, m in retr.items():
        print(f"  {name:<16} " + " ".join(f"{k}={v}" for k, v in m.items()))

    print("\n=== BLEU + BERTScore (gen configs) ===")
    gen, spot = score_generation(out_dir)

    # verify (user-requested): every gen config has a populated per-config mean
    # F1 in the sane Thai-BERTScore range, and per-item F1 was retained.
    for name, m in gen.items():
        f1 = m.get("bertscore_f1")
        assert isinstance(f1, float), f"{name}: bertscore_f1 is None/missing"
        assert 0.7 <= f1 <= 0.95, f"{name}: mean F1 {f1} outside ~0.7-0.95"
        by_item = m.get("bertscore_f1_by_item")
        assert isinstance(by_item, dict) and by_item, f"{name}: no per-item F1"
    print(f"  [verify] {len(gen)} gen configs: all F1 populated + in range OK")

    for name, m in gen.items():
        print(
            f"  {name:<22} BLEU={m['bleu']:>5} "
            f"BLEU1-4={m['bleu_1']}/{m['bleu_2']}/{m['bleu_3']}/{m['bleu_4']} "
            f"BERTScoreF1={m['bertscore_f1_mean']}"
        )

    print("\n=== spot-check (F): gen_baseline first 3 ===")
    for s in spot:
        print(json.dumps(s, ensure_ascii=False))

    summary = {
        "phase": "addmetrics",
        "provenance": prov,
        "sanity": sanity,
        "precision_retrieval": retr,
        "bleu_bertscore_generation": gen,
        "spot_check": spot,
    }
    path = out_dir / "_summary_addmetrics.json"
    path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nsummary -> {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
