"""KG-compare Phase 3 — score both RAGs with the SAME metrics + Claude judge.

Loads the two answer runs (vector_subset, graphrag), joins gold, and for every
ANSWERED item runs the independent Claude judge (correctness + faithfulness) plus
sentence-BLEU vs the gold answer. Refusals are scored by role (correct behaviour
= refuse on out-of-subset / rejection; = answer on in-subset). Writes a
per-question record, a summary JSON, and ``benchmark/kg_comparison.xlsx``.

Never overwrites ``final_comparison.xlsx`` (isolation §0).

Run inside the backend container:
    docker compose exec backend python -m eval.kg_compare.score
"""

from __future__ import annotations

import json
import statistics
from pathlib import Path
from typing import Any

from eval.datasets import load_eval_items
from eval.kg_compare.claude_judge import ClaudeJudge
from eval.metrics.text_metrics import sentence_bleu

HERE = Path(__file__).resolve().parent
RUNS = HERE.parent / "runs" / "kg_compare"
VECTOR = RUNS / "vector_subset" / "results.jsonl"
GRAPH = RUNS / "graphrag" / "results.jsonl"
BUILD_STATS = RUNS / "graphrag" / "kg_build_stats.json"
SCORED = RUNS / "scored.jsonl"
SUMMARY = RUNS / "_summary_comparison.json"
XLSX = HERE.parent.parent.parent / "benchmark" / "kg_comparison.xlsx"


def _load(path: Path) -> dict[int, dict[str, Any]]:
    return {
        (r := json.loads(line))["item_id"]: r
        for line in path.open(encoding="utf-8")
    }


def _context_text(rec: dict[str, Any]) -> str:
    if "evidence" in rec:  # vector run
        return "\n\n".join(e.get("text", "") for e in rec.get("evidence", []))
    return rec.get("context", "")  # graphrag run


def _mean(xs: list[float]) -> float:
    return round(statistics.fmean(xs), 4) if xs else 0.0


def score_run(
    name: str,
    run: dict[int, dict[str, Any]],
    gold: dict[int, Any],
    judge: ClaudeJudge,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for qid, rec in sorted(run.items()):
        item = gold[qid]
        role = rec.get("role", "")
        answered = rec.get("status") == "answered" and not rec.get("refused")
        correct_behavior = answered if role == "in_subset" else (not answered)
        row: dict[str, Any] = {
            "rag": name,
            "item_id": qid,
            "role": role,
            "status": rec.get("status"),
            "answered": answered,
            "correct_behavior": correct_behavior,
        }
        if answered:
            v = judge.judge(
                question=item.question,
                gold=item.gold_answer,
                answer=rec.get("answer", ""),
                context=_context_text(rec),
            )
            row.update(
                correctness=v.correctness,
                faithfulness=v.faithfulness,
                verdict=v.verdict,
                bleu=round(sentence_bleu(rec.get("answer", ""), item.gold_answer), 2),
                judge_note=v.note,
                judge_error=v.error,
            )
            # An answer that is confidently wrong = hallucination signal.
            row["hallucination"] = answered and v.correctness < 0.5
        else:
            row.update(correctness=None, faithfulness=None, verdict="refused", bleu=None,
                       hallucination=False)
        out.append(row)
        print(f"  [{name:>8}] q{qid:>2} {role:>13} "
              f"{'ANS' if answered else 'ref':>3} "
              f"corr={row.get('correctness')} faith={row.get('faithfulness')}")
    return out


def aggregate(name: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_role: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        by_role.setdefault(r["role"], []).append(r)

    def agg(role: str) -> dict[str, Any]:
        rs = by_role.get(role, [])
        ans = [r for r in rs if r["answered"]]
        return {
            "n": len(rs),
            "answered": len(ans),
            "refused": len(rs) - len(ans),
            "correct_behavior_rate": _mean([1.0 if r["correct_behavior"] else 0.0 for r in rs]),
            "mean_correctness_answered": _mean([r["correctness"] for r in ans if r["correctness"] is not None]),
            "mean_faithfulness_answered": _mean([r["faithfulness"] for r in ans if r["faithfulness"] is not None]),
            "mean_bleu_answered": _mean([r["bleu"] for r in ans if r["bleu"] is not None]),
            "hallucinations": sum(1 for r in rs if r.get("hallucination")),
        }

    return {"rag": name, "in_subset": agg("in_subset"),
            "rejection": agg("rejection"), "out_of_subset": agg("out_of_subset")}


def write_xlsx(scored: list[dict[str, Any]], summaries: list[dict[str, Any]],
               build: dict[str, Any]) -> None:
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill

    wb = Workbook()
    # --- Summary sheet ---
    ws = wb.active
    ws.title = "summary"
    bold = Font(bold=True)
    fill = PatternFill("solid", fgColor="DDEBE9")
    ws.append(["KG comparison — Vector RAG vs GraphRAG (LightRAG)"])
    ws["A1"].font = Font(bold=True, size=13)
    ws.append([])
    ws.append(["Cost axis (index-time)", "Vector RAG", "GraphRAG"])
    for c in ws[ws.max_row]:
        c.font = bold; c.fill = fill
    cost = build.get("llm_extraction_cost_from_cache", {})
    ws.append(["index LLM calls", 0, cost.get("llm_calls", "?")])
    ws.append(["index tokens (est)", 0, cost.get("total_tokens_est", "?")])
    ws.append(["graph nodes / edges", "—", f"{build.get('graph',{}).get('n_nodes','?')} / {build.get('graph',{}).get('n_edges','?')}"])
    ws.append([])
    hdr = ["role", "metric", "Vector RAG", "GraphRAG"]
    ws.append(hdr)
    for c in ws[ws.max_row]:
        c.font = bold; c.fill = fill
    vec = next(s for s in summaries if s["rag"] == "vector")
    gra = next(s for s in summaries if s["rag"] == "graphrag")
    for role in ("in_subset", "rejection", "out_of_subset"):
        for metric in ("n", "answered", "refused", "correct_behavior_rate",
                       "mean_correctness_answered", "mean_faithfulness_answered",
                       "mean_bleu_answered", "hallucinations"):
            ws.append([role, metric, vec[role][metric], gra[role][metric]])

    # --- Per-question sheet ---
    ws2 = wb.create_sheet("per_question")
    cols = ["rag", "item_id", "role", "status", "answered", "correct_behavior",
            "correctness", "faithfulness", "verdict", "bleu", "hallucination", "judge_note"]
    ws2.append(cols)
    for c in ws2[1]:
        c.font = bold; c.fill = fill
    for r in scored:
        ws2.append([r.get(k) for k in cols])
    for col in ws2.columns:
        w = max((len(str(c.value)) for c in col if c.value is not None), default=10)
        ws2.column_dimensions[col[0].column_letter].width = min(60, max(8, w + 2))

    XLSX.parent.mkdir(parents=True, exist_ok=True)
    wb.save(XLSX)


def main() -> int:
    gold = {it.id: it for it in load_eval_items()}
    vector = _load(VECTOR)
    graph = _load(GRAPH)
    build = json.loads(BUILD_STATS.read_text(encoding="utf-8")) if BUILD_STATS.exists() else {}

    print("judging with Claude (independent of the Gemini answer model)…")
    judge = ClaudeJudge()
    scored = score_run("vector", vector, gold, judge) + score_run("graphrag", graph, gold, judge)

    with SCORED.open("w", encoding="utf-8") as fh:
        for r in scored:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")

    summaries = [
        aggregate("vector", [r for r in scored if r["rag"] == "vector"]),
        aggregate("graphrag", [r for r in scored if r["rag"] == "graphrag"]),
    ]
    SUMMARY.write_text(json.dumps({"summaries": summaries, "cost": build.get("llm_extraction_cost_from_cache", {})},
                                  ensure_ascii=False, indent=2), encoding="utf-8")
    write_xlsx(scored, summaries, build)

    print("\n=== SUMMARY ===")
    for s in summaries:
        print(f"\n[{s['rag']}]")
        for role in ("in_subset", "rejection", "out_of_subset"):
            a = s[role]
            print(f"  {role:>13}: behavior_ok={a['correct_behavior_rate']} "
                  f"correctness={a['mean_correctness_answered']} "
                  f"faith={a['mean_faithfulness_answered']} bleu={a['mean_bleu_answered']} "
                  f"halluc={a['hallucinations']}")
    print(f"\nwrote -> {SCORED}\nwrote -> {SUMMARY}\nwrote -> {XLSX}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
