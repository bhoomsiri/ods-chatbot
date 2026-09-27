"""Summarise the JMeter twin-endpoint perf run (spec §8.3).

Reads the two JTL files (vector vs KG) and reports, per phase:
  - total latency (elapsed) p50/p90/p95/p99
  - TTFT (JMeter `Latency` = time to first SSE byte = first token) p50/p95
  - throughput (Load phase: completed / wall-clock) + error rate
Writes ``benchmark/kg_perf_report.md``. Pure stdlib; run on host or in container.
"""

from __future__ import annotations

import csv
import statistics
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
PERF = HERE.parent / "runs" / "kg_compare" / "perf"
REPORT = HERE.parent.parent.parent / "benchmark" / "kg_perf_report.md"


def _pct(xs: list[float], p: float) -> float:
    if not xs:
        return 0.0
    xs = sorted(xs)
    k = (len(xs) - 1) * p
    lo, hi = int(k), min(int(k) + 1, len(xs) - 1)
    return round(xs[lo] + (xs[hi] - xs[lo]) * (k - lo), 1)


def load(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            rows.append(r)
    return rows


def phase_of(label: str) -> str:
    return "baseline" if label.strip().lower().startswith("q") else "load"


def stats(rows: list[dict[str, Any]]) -> dict[str, Any]:
    elapsed = [float(r["elapsed"]) for r in rows]
    ttft = [float(r.get("Latency", r["elapsed"])) for r in rows]
    ok = sum(1 for r in rows if r.get("success", "true") == "true")
    n = len(rows)
    span_s = 0.0
    if rows:
        ts = [int(r["timeStamp"]) for r in rows]
        span_s = max(1.0, (max(ts) + int(rows[-1]["elapsed"]) - min(ts)) / 1000.0)
    return {
        "n": n,
        "errors": n - ok,
        "error_pct": round(100 * (n - ok) / n, 1) if n else 0.0,
        "lat_p50": _pct(elapsed, 0.50),
        "lat_p90": _pct(elapsed, 0.90),
        "lat_p95": _pct(elapsed, 0.95),
        "lat_p99": _pct(elapsed, 0.99),
        "lat_mean": round(statistics.fmean(elapsed), 1) if elapsed else 0.0,
        "ttft_p50": _pct(ttft, 0.50),
        "ttft_p95": _pct(ttft, 0.95),
        "throughput_rps": round(n / span_s, 3) if span_s else 0.0,
    }


def summarise(path: Path) -> dict[str, Any]:
    rows = load(path)
    by = {"baseline": [], "load": [], "all": rows}
    for r in rows:
        by[phase_of(r.get("label", ""))].append(r)
    return {ph: stats(rs) for ph, rs in by.items()}


def _row(metric: str, *cells: Any) -> str:
    return f"| {metric} | " + " | ".join(str(c) for c in cells) + " |"


def main() -> int:
    vec = summarise(PERF / "vec.jtl")
    kg = summarise(PERF / "kg.jtl")
    # Hierarchical is optional: report 3-way when pc.jtl exists, else 2-way.
    has_pc = (PERF / "pc.jtl").exists()
    pc = summarise(PERF / "pc.jtl") if has_pc else None

    def block(title: str, ph: str) -> list[str]:
        v, k = vec[ph], kg[ph]
        p = pc[ph] if pc else None
        cols = ["Vector RAG", "GraphRAG"] + (["Hierarchical"] if p else [])

        def trip(key: str) -> list[Any]:
            return [v[key], k[key]] + ([p[key]] if p else [])

        return [
            f"### {title}",
            "| metric | " + " | ".join(cols) + " |",
            "|---|" + "---:|" * len(cols),
            _row("requests", *trip("n")),
            _row("error %", *trip("error_pct")),
            _row("TTFT p50 (ms)", *trip("ttft_p50")),
            _row("TTFT p95 (ms)", *trip("ttft_p95")),
            _row("total latency p50 (ms)", *trip("lat_p50")),
            _row("total latency p95 (ms)", *trip("lat_p95")),
            _row("total latency p99 (ms)", *trip("lat_p99")),
            _row("throughput (req/s)", *trip("throughput_rps")),
            "",
        ]

    faster = round(kg["baseline"]["lat_p50"] / max(1, vec["baseline"]["lat_p50"]), 1)
    title = "Vector RAG vs GraphRAG vs Hierarchical" if pc else "Vector RAG vs GraphRAG"
    endpoints = "`/vec/chat` = Qdrant subset, `/kg/chat` = LightRAG mix" + (
        ", `/pc/chat` = parent-child" if pc else ""
    )
    pc_note = ""
    if pc:
        pc_fast = round(pc["baseline"]["lat_p50"] / max(1, vec["baseline"]["lat_p50"]), 2)
        pc_note = (
            f" Hierarchical ≈ {pc_fast}× Vector's latency (no LLM/graph step in "
            "retrieval), i.e. close to Vector and far below GraphRAG."
        )
    lines = [
        f"# JMeter perf — {title} (twin/triple endpoint, spec §8)",
        "",
        f"> **Result: Vector RAG ~{faster}× faster than GraphRAG (total latency p50).**"
        + pc_note,
        "> Both share the identical generator; only the retriever differs, so the gap",
        "> reflects retrieval architecture, not endpoint quality.",
        "",
        "Same serving stack, same answer model (gemini-2.5-flash), same SSE generator —",
        f"**only the retriever differs** ({endpoints}).",
        "JMeter `Latency` = first SSE byte ≈ **TTFT**; `elapsed` = total stream time.",
        "Load is light (indicative, not a stress test) to control Gemini cost.",
        "",
        *block("Baseline (1 user, sequential)", "baseline"),
        *block("Load (concurrent users)", "load"),
        "## Notes / threats to validity",
        "- All endpoints share one generator; the gap reflects retrieval architecture.",
        "- GraphRAG's `mix` feeds a large graph context to the generator — an inherent",
        "  cost of the approach, not a serving artefact.",
        "- Hierarchical adds only a child→parent lookup + rerank (no LLM in retrieval),",
        "  so its latency tracks Vector's.",
        "- Light load → indicative percentiles, not a saturation/stress result (§8.4).",
        "- Warmup requests were sent before measurement to cut the ~20-30s cold start.",
        "",
    ]
    REPORT.write_text("\n".join(lines), encoding="utf-8")
    print("VEC:", vec["all"])
    print("KG :", kg["all"])
    if pc:
        print("PC :", pc["all"])
    print("wrote ->", REPORT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
