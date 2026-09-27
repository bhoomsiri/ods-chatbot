"""Build the multi-sheet Excel comparison from every saved summary (no re-run).

Consolidates retrieval / generation / rejection / add-metrics / RAGAS summaries
into ``runs/ablation_addmetrics.xlsx`` with the five comparison views the spec
asks for:

1. PerConfig     — every metric per config, winners highlighted per column.
2. RetrievedVsGold — per question: the actual top chunks (id/page/source/score/
   text, fetched from Qdrant) vs gold pages/answer.
3. AcrossConfigs — a few probe items (1, 28, 30) across configs.
4. JudgeCompare  — Gemini-Flash vs Claude per item + Pearson/Spearman.
5. ExpertSlots   — empty columns to fill when the 3rd expert scores arrive.
Plus a Provenance sheet (library/model versions, judges, dates).

Usage (container with openpyxl):
    python -m eval.report_addmetrics
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from eval.datasets import load_eval_items
from eval.metrics.correlation import pearson, spearman

RUNS_DIR = Path(__file__).resolve().parent / "runs"
PROBE_ITEMS = (1, 28, 30)


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as fh:
        return [json.loads(line) for line in fh]


def _provenance_sheet(wb: Any, summaries: dict[str, dict[str, Any]]) -> None:
    ws = wb.active
    ws.title = "Provenance"
    ws.append(["summary", "key", "value"])
    for name, s in summaries.items():
        prov = s.get("provenance", {})
        if isinstance(prov, dict):
            for k, v in prov.items():
                ws.append(
                    [
                        name,
                        k,
                        json.dumps(v, ensure_ascii=False)
                        if isinstance(v, dict)
                        else str(v),
                    ]
                )
        if "sanity" in s:
            for k, v in s["sanity"].items():
                ws.append([name, f"sanity.{k}", str(v)])


def _per_config_sheet(wb: Any, summaries: dict[str, dict[str, Any]]) -> None:
    from openpyxl.styles import PatternFill

    retr = {r["config"]: r for r in summaries.get("retrieval", {}).get("rows", [])}
    src = summaries.get("source", {}).get("rows", {})
    rej = {r["config"]: r for r in summaries.get("rejection", {}).get("rows", [])}
    gen = {r["config"]: r for r in summaries.get("generation", {}).get("rows", [])}
    add = summaries.get("addmetrics", {})
    prec = add.get("precision_retrieval", {})
    bleu = add.get("bleu_bertscore_generation", {})
    ragas = summaries.get("ragas", {})
    ctx = ragas.get("context_metrics", {})
    regen = ragas.get("regen_judge", {})

    ws = wb.create_sheet("PerConfig")
    headers = [
        "config",
        "knob",
        "src_hit@5",
        "recall@5(page)",
        "precision_src@1",
        "mrr",
        "ctx_precision",
        "ctx_recall",
        "neg_rejection",
        "false_refusal",
        "bleu",
        "bertscore_f1",
        "flash_faith",
        "claude_faith",
        "flash_relev",
        "claude_relev",
    ]
    ws.append(headers)

    names = sorted(set(retr) | set(gen))
    for name in names:
        r = retr.get(name, {})
        rm = r.get("metrics", {})
        # generation summary is keyed by cfg.name (no "gen_" prefix); the
        # add-metrics + RAGAS summaries are keyed by the run dir ("gen_<name>").
        g = gen.get(name, {})
        row = [
            name,
            r.get("knob", g.get("knob", "")),
            src.get(name, {}).get("src_hit@5"),
            rm.get("recall@5"),
            prec.get(name, {}).get("precision_src@1"),
            rm.get("mrr"),
            ctx.get(name, {}).get("context_precision"),
            ctx.get(name, {}).get("context_recall"),
            rej.get(name, {}).get("negative_rejection_rate"),
            rej.get(name, {}).get("false_refusal_rate"),
            bleu.get(f"gen_{name}", {}).get("bleu"),
            bleu.get(f"gen_{name}", {}).get("bertscore_f1_mean"),
            g.get("faithfulness_mean"),
            regen.get(f"gen_{name}", {}).get("claude_faithfulness"),
            g.get("answer_relevancy_mean"),
            regen.get(f"gen_{name}", {}).get("claude_answer_relevancy"),
        ]
        ws.append(row)

    # highlight the max in each numeric column (winners)
    fill = PatternFill(start_color="C6EFCE", end_color="C6EFCE", fill_type="solid")
    for col in range(3, len(headers) + 1):
        vals = []
        for r_i in range(2, ws.max_row + 1):
            v = ws.cell(row=r_i, column=col).value
            if isinstance(v, int | float):
                vals.append((v, r_i))
        if not vals:
            continue
        best = max(vals)[0]
        for v, r_i in vals:
            if v == best:
                ws.cell(row=r_i, column=col).fill = fill


def _retrieved_vs_gold_sheet(wb: Any, out_dir: Path) -> None:
    items = {it.id: it for it in load_eval_items()}
    fetcher = _make_fetcher()
    ws = wb.create_sheet("RetrievedVsGold")
    ws.append(
        [
            "item_id",
            "question",
            "gold_pages",
            "gold_answer",
            "rank",
            "chunk_id",
            "page",
            "source",
            "score",
            "chunk_text",
        ]
    )
    for rec in _read_jsonl(out_dir / "baseline" / "results.jsonl"):
        item = items.get(int(rec["item_id"]))
        if item is None:
            continue
        reranked = rec.get("reranked", [])[:5]
        texts = fetcher([str(c["id"]) for c in reranked]) if fetcher else {}
        for rank, c in enumerate(reranked, start=1):
            ws.append(
                [
                    item.id,
                    item.question if rank == 1 else "",
                    ";".join(map(str, sorted(item.gold_pages))) if rank == 1 else "",
                    item.gold_answer[:300] if rank == 1 else "",
                    rank,
                    c["id"],
                    c.get("page"),
                    c.get("source"),
                    round(float(c.get("score", 0)), 4),
                    texts.get(str(c["id"]), "")[:400],
                ]
            )


def _across_configs_sheet(wb: Any, out_dir: Path) -> None:
    items = {it.id: it for it in load_eval_items()}
    ws = wb.create_sheet("AcrossConfigs")
    ws.append(["item_id", "config", "top1_source", "top1_score", "n_evidence_pages"])
    for d in sorted(out_dir.iterdir()):
        if d.name.startswith("gen_") or not (d / "results.jsonl").exists():
            continue
        for rec in _read_jsonl(d / "results.jsonl"):
            if int(rec["item_id"]) not in PROBE_ITEMS:
                continue
            reranked = rec.get("reranked", [])
            top = reranked[0] if reranked else {}
            ws.append(
                [
                    rec["item_id"],
                    d.name,
                    top.get("source", ""),
                    round(float(top.get("score", 0)), 4),
                    len(rec.get("evidence_pages", [])),
                ]
            )
    _ = items  # kept for symmetry / future gold columns


def _judge_compare_sheet(wb: Any, summaries: dict[str, dict[str, Any]]) -> None:
    pairs = summaries.get("ragas", {}).get("judge_pairs", [])
    ws = wb.create_sheet("JudgeCompare")
    ws.append(
        [
            "config",
            "item_id",
            "flash_faith",
            "claude_faith",
            "flash_relev",
            "claude_relev",
        ]
    )
    ff, cf, fr, cr = [], [], [], []
    for p in pairs:
        ws.append(
            [
                p.get("config"),
                p.get("item_id"),
                p.get("flash_faithfulness"),
                p.get("claude_faithfulness"),
                p.get("flash_answer_relevancy"),
                p.get("claude_answer_relevancy"),
            ]
        )
        if isinstance(p.get("flash_faithfulness"), int | float) and isinstance(
            p.get("claude_faithfulness"), int | float
        ):
            ff.append(float(p["flash_faithfulness"]))
            cf.append(float(p["claude_faithfulness"]))
        if isinstance(p.get("flash_answer_relevancy"), int | float) and isinstance(
            p.get("claude_answer_relevancy"), int | float
        ):
            fr.append(float(p["flash_answer_relevancy"]))
            cr.append(float(p["claude_answer_relevancy"]))
    ws.append([])
    ws.append(["correlation", "metric", "pearson", "spearman", "n"])
    ws.append(
        [
            "",
            "faithfulness",
            round(pearson(ff, cf), 4),
            round(spearman(ff, cf), 4),
            len(ff),
        ]
    )
    ws.append(
        [
            "",
            "answer_relevancy",
            round(pearson(fr, cr), 4),
            round(spearman(fr, cr), 4),
            len(fr),
        ]
    )


def _expert_slots_sheet(wb: Any) -> None:
    ws = wb.create_sheet("ExpertSlots")
    ws.append(
        ["item_id", "question", "expert_faithfulness", "expert_relevancy", "expert_notes"]
    )
    for it in load_eval_items():
        ws.append([it.id, it.question, "", "", ""])


def _make_fetcher() -> Any:
    try:
        from eval.score_ragas import QdrantContextFetcher

        f = QdrantContextFetcher("ods_chunks_v3")

        def fetch(ids: list[str]) -> dict[str, str]:
            texts = f.texts(ids)
            # texts() drops empties; re-pair best-effort by re-fetching individually
            out: dict[str, str] = {}
            for i in ids:
                t = f.texts([i])
                out[i] = t[0] if t else ""
            _ = texts
            return out

        return fetch
    except Exception:
        return None


def main(argv: Sequence[str] | None = None) -> int:
    from openpyxl import Workbook

    parser = argparse.ArgumentParser(description="Build add-metrics Excel report")
    parser.add_argument("--out", default=str(RUNS_DIR))
    args = parser.parse_args(argv)
    out_dir = Path(args.out)

    summaries = {
        "retrieval": _load(out_dir / "_summary_retrieval.json"),
        "source": _load(out_dir / "_summary_source.json"),
        "generation": _load(out_dir / "_summary_generation.json"),
        "rejection": _load(out_dir / "_summary_rejection.json"),
        "addmetrics": _load(out_dir / "_summary_addmetrics.json"),
        "ragas": _load(out_dir / "_summary_ragas.json"),
    }

    wb = Workbook()
    _provenance_sheet(wb, summaries)
    _per_config_sheet(wb, summaries)
    _retrieved_vs_gold_sheet(wb, out_dir)
    _across_configs_sheet(wb, out_dir)
    _judge_compare_sheet(wb, summaries)
    _expert_slots_sheet(wb)

    path = out_dir / "ablation_addmetrics.xlsx"
    wb.save(path)
    print(f"workbook -> {path} ({len(wb.sheetnames)} sheets: {wb.sheetnames})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
