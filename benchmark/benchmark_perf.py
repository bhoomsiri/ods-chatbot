#!/usr/bin/env python3
"""
benchmark_perf.py — Black-box performance test for the ODS RAG chatbot.

วัด "ประสิทธิภาพระบบ" (ความเร็ว/throughput/ต้นทุนโดยประมาณ) ของ endpoint
POST /api/chat (Server-Sent Events) โดยไม่แตะโค้ด backend.

วัดอะไร (ต่อคำถาม):
  - TTFT (time-to-first-token): เวลาตั้งแต่ส่ง request จนได้ token แรก
  - total latency: เวลาจนจบ (event "done")
  - stream duration: เวลาตั้งแต่ token แรกถึง token สุดท้าย
  - จำนวนตัวอักษร/โทเคนของคำตอบ (โดยประมาณ) และจำนวน citation
รันซ้ำหลายรอบต่อข้อ (ตัด warmup รอบแรกทิ้ง) แล้วสรุป mean/median/p95/p99/sd
จากนั้นทำ load test (ยิงพร้อมกันหลายระดับ concurrency) วัด throughput และ
latency ตอนรับโหลด

ผลลัพธ์:
  - perf_raw.csv         : ทุก request ทุกข้อทุกรอบ (ข้อมูลดิบ)
  - perf_summary.xlsx    : sheet Config / PerQuestion / Overall / LoadTest + กราฟ

การใช้งาน:
  1) เปิด backend ให้รันอยู่ (uvicorn app.main:app)  และมี Qdrant/Gemini พร้อม
  2) pip install httpx openpyxl
  3) แก้ค่าใน CONFIG ด้านล่างให้ตรงกับระบบคุณ (โดยเฉพาะ BASE_URL, โมเดล, ราคา)
  4) python benchmark_perf.py
"""

from __future__ import annotations

import asyncio
import csv
import json
import statistics
import sys
from dataclasses import dataclass, field
from pathlib import Path
from time import perf_counter

try:
    import httpx
except ImportError:
    sys.exit("ต้องติดตั้งก่อน:  pip install httpx openpyxl")

# ============================ CONFIG (แก้ตรงนี้) ============================
BASE_URL = "http://localhost:8000"      # ที่อยู่ backend
ENDPOINT = "/api/chat"
HEADERS = {"X-Client-Id": "benchmark"}  # scope conversation ของการทดสอบ
CATEGORY = None                          # ตั้งค่าหมวด (ถ้าต้องการกรอง) มิฉะนั้น None
DEPARTMENT = None

QUESTIONS_FILE = Path(__file__).with_name("questions.json")
OUT_DIR = Path(__file__).parent

ROUNDS = 5            # จำนวนรอบต่อคำถาม (รวม warmup)
WARMUP = 1            # ตัดผลรอบแรก ๆ ออกกี่รอบ (กัน cold start)
REQUEST_TIMEOUT = 120 # วินาที

# Load test: ยิงพร้อมกันที่ระดับ concurrency เหล่านี้
RUN_LOAD_TEST = True
LOAD_LEVELS = [1, 2, 4, 8]
LOAD_REQUESTS_PER_LEVEL = 16   # จำนวน request รวมที่ยิงในแต่ละระดับ

# ประมาณการต้นทุน (ตรวจสอบ "ราคาปัจจุบัน" จาก Google AI / Vertex pricing เสมอ)
MODEL_NAME = "gemini-2.5-flash"
PRICE_OUTPUT_PER_1M_USD = 0.0   # ใส่ราคา output token (USD ต่อ 1M tokens)
PRICE_INPUT_PER_1M_USD = 0.0    # input ประเมิน black-box ไม่ได้ (ดู note)
USD_TO_THB = 36.5
CHARS_PER_OUTPUT_TOKEN = 2.0    # ตัวคูณประมาณ token ของภาษาไทย (หยาบ ๆ)
# ===========================================================================


@dataclass
class Result:
    qid: int
    category: str
    round: int
    warmup: bool
    ok: bool
    ttft: float | None = None
    total: float | None = None
    stream: float | None = None
    out_chars: int = 0
    out_tokens_est: float = 0.0
    n_citations: int = 0
    error: str | None = None


def load_questions() -> list[dict]:
    if not QUESTIONS_FILE.exists():
        sys.exit(f"ไม่พบไฟล์คำถาม: {QUESTIONS_FILE}")
    return json.loads(QUESTIONS_FILE.read_text(encoding="utf-8"))


async def one_request(client: httpx.AsyncClient, q: dict, rnd: int, warmup: bool) -> Result:
    payload = {"message": q["question"]}
    if CATEGORY:
        payload["category"] = CATEGORY
    if DEPARTMENT:
        payload["department"] = DEPARTMENT

    r = Result(qid=q["id"], category=q.get("category", ""), round=rnd, warmup=warmup, ok=False)
    parts: list[str] = []
    t_start = perf_counter()
    try:
        async with client.stream("POST", BASE_URL + ENDPOINT, json=payload, headers=HEADERS,
                                 timeout=REQUEST_TIMEOUT) as resp:
            if resp.status_code != 200:
                r.error = f"HTTP {resp.status_code}"
                return r
            t_last = t_start
            async for line in resp.aiter_lines():
                if not line or not line.startswith("data:"):
                    continue
                try:
                    evt = json.loads(line[5:].strip())
                except json.JSONDecodeError:
                    continue
                typ = evt.get("type")
                if typ == "token":
                    now = perf_counter()
                    if r.ttft is None:
                        r.ttft = now - t_start
                    t_last = now
                    parts.append(evt.get("text", ""))
                elif typ == "citations":
                    r.n_citations = len(evt.get("citations", []))
                elif typ == "done":
                    r.total = perf_counter() - t_start
                    r.ok = True
                    break
                elif typ == "error":
                    r.error = evt.get("detail", "stream error")
                    return r
            if r.total is None:  # stream ended without explicit "done"
                r.total = perf_counter() - t_start
                r.ok = bool(parts)
            text = "".join(parts)
            r.out_chars = len(text)
            r.out_tokens_est = round(len(text) / CHARS_PER_OUTPUT_TOKEN, 1)
            if r.ttft is not None:
                r.stream = round(t_last - t_start - r.ttft, 4)
    except Exception as e:  # noqa: BLE001 - benchmark client tolerates any failure
        r.error = f"{type(e).__name__}: {e}"
    return r


async def run_sequential(client: httpx.AsyncClient, questions: list[dict]) -> list[Result]:
    results: list[Result] = []
    total = len(questions) * ROUNDS
    done = 0
    for rnd in range(1, ROUNDS + 1):
        warm = rnd <= WARMUP
        for q in questions:
            res = await one_request(client, q, rnd, warm)
            results.append(res)
            done += 1
            tag = "warmup" if warm else "measure"
            status = f"{res.total:.2f}s ttft={res.ttft:.2f}s" if res.ok else f"ERR {res.error}"
            print(f"[{done:>3}/{total}] ({tag}) Q{res.qid:<2} {status}")
    return results


async def run_load(client: httpx.AsyncClient, questions: list[dict], level: int) -> dict:
    sem = asyncio.Semaphore(level)
    lat: list[float] = []
    errors = 0

    async def task(q: dict) -> None:
        nonlocal errors
        async with sem:
            res = await one_request(client, q, rnd=0, warmup=False)
            if res.ok and res.total is not None:
                lat.append(res.total)
            else:
                errors += 1

    qs = [questions[i % len(questions)] for i in range(LOAD_REQUESTS_PER_LEVEL)]
    t0 = perf_counter()
    await asyncio.gather(*(task(q) for q in qs))
    wall = perf_counter() - t0
    ok = len(lat)
    return {
        "concurrency": level,
        "requests": LOAD_REQUESTS_PER_LEVEL,
        "ok": ok,
        "errors": errors,
        "wall_s": round(wall, 3),
        "throughput_rps": round(ok / wall, 3) if wall else 0,
        "lat_mean": round(statistics.mean(lat), 3) if lat else None,
        "lat_p50": round(pct(lat, 50), 3) if lat else None,
        "lat_p95": round(pct(lat, 95), 3) if lat else None,
        "lat_max": round(max(lat), 3) if lat else None,
    }


def pct(data: list[float], p: float) -> float:
    if not data:
        return 0.0
    s = sorted(data)
    k = (len(s) - 1) * (p / 100)
    lo, hi = int(k), min(int(k) + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


def agg(values: list[float]) -> dict:
    vals = [v for v in values if v is not None]
    if not vals:
        return {"n": 0, "mean": None, "p50": None, "p95": None, "p99": None, "sd": None}
    return {
        "n": len(vals),
        "mean": round(statistics.mean(vals), 3),
        "p50": round(pct(vals, 50), 3),  # median
        "p95": round(pct(vals, 95), 3),
        "p99": round(pct(vals, 99), 3),
        "sd": round(statistics.stdev(vals), 3) if len(vals) > 1 else 0.0,
    }


def write_csv(results: list[Result]) -> Path:
    path = OUT_DIR / "perf_raw.csv"
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["qid", "category", "round", "warmup", "ok", "ttft_s", "total_s",
                    "stream_s", "out_chars", "out_tokens_est", "n_citations", "error"])
        for r in results:
            w.writerow([r.qid, r.category, r.round, r.warmup, r.ok, r.ttft, r.total,
                        r.stream, r.out_chars, r.out_tokens_est, r.n_citations, r.error or ""])
    return path


def write_xlsx(results: list[Result], load_rows: list[dict]) -> Path:
    from openpyxl import Workbook
    from openpyxl.chart import BarChart, Reference
    from openpyxl.styles import Font, PatternFill, Alignment

    measured = [r for r in results if not r.warmup and r.ok]
    head_fill = PatternFill("solid", fgColor="1F3864")
    head_font = Font(color="FFFFFF", bold=True)

    def style_header(ws, ncols: int) -> None:
        for c in range(1, ncols + 1):
            cell = ws.cell(row=1, column=c)
            cell.fill = head_fill
            cell.font = head_font
            cell.alignment = Alignment(horizontal="center")

    wb = Workbook()

    # --- Config sheet ---
    ws = wb.active
    ws.title = "Config"
    cfg = [
        ["พารามิเตอร์", "ค่า"],
        ["BASE_URL", BASE_URL + ENDPOINT],
        ["MODEL_NAME", MODEL_NAME],
        ["ROUNDS (รวม warmup)", ROUNDS],
        ["WARMUP (ตัดทิ้ง)", WARMUP],
        ["จำนวนคำถาม", len({r.qid for r in results})],
        ["request ที่นำมาคิดผล", len(measured)],
        ["LOAD_LEVELS", str(LOAD_LEVELS) if RUN_LOAD_TEST else "ปิด"],
        ["PRICE_OUTPUT_PER_1M_USD", PRICE_OUTPUT_PER_1M_USD],
        ["CHARS_PER_OUTPUT_TOKEN (ประมาณ)", CHARS_PER_OUTPUT_TOKEN],
        ["หมายเหตุ", "ต้นทุน input ประเมินแบบ black-box ไม่ได้ — ดู spec per-stage timing"],
    ]
    for row in cfg:
        ws.append(row)
    style_header(ws, 2)
    ws.column_dimensions["A"].width = 32
    ws.column_dimensions["B"].width = 48

    # --- PerQuestion sheet ---
    ws = wb.create_sheet("PerQuestion")
    ws.append(["qid", "category", "n", "total_mean", "total_p50", "total_p95",
               "ttft_mean", "ttft_p50", "ttft_p95", "stream_mean",
               "out_chars_mean", "cit_mean"])
    by_q: dict[int, list[Result]] = {}
    for r in measured:
        by_q.setdefault(r.qid, []).append(r)
    for qid in sorted(by_q):
        rs = by_q[qid]
        tot = agg([r.total for r in rs])
        ttft = agg([r.ttft for r in rs])
        strm = agg([r.stream for r in rs])
        chars = statistics.mean([r.out_chars for r in rs]) if rs else 0
        cits = statistics.mean([r.n_citations for r in rs]) if rs else 0
        ws.append([qid, rs[0].category, tot["n"], tot["mean"], tot["p50"], tot["p95"],
                   ttft["mean"], ttft["p50"], ttft["p95"], strm["mean"],
                   round(chars, 1), round(cits, 2)])
    style_header(ws, 12)
    ws.column_dimensions["B"].width = 24

    # chart: total_mean per question
    if by_q:
        chart = BarChart()
        chart.title = "Total latency เฉลี่ยต่อคำถาม (วินาที)"
        chart.y_axis.title = "วินาที"
        chart.x_axis.title = "qid"
        data = Reference(ws, min_col=4, min_row=1, max_row=ws.max_row)
        cats = Reference(ws, min_col=1, min_row=2, max_row=ws.max_row)
        chart.add_data(data, titles_from_data=True)
        chart.set_categories(cats)
        chart.height, chart.width = 9, 20
        ws.add_chart(chart, "L2")

    # --- Overall sheet ---
    ws = wb.create_sheet("Overall")
    ws.append(["metric", "n", "mean", "p50", "p95", "p99", "sd"])
    for label, key in [("total_latency_s", "total"), ("ttft_s", "ttft"), ("stream_s", "stream")]:
        a = agg([getattr(r, key) for r in measured])
        ws.append([label, a["n"], a["mean"], a["p50"], a["p95"], a["p99"], a["sd"]])
    # cost estimate
    out_tokens = [r.out_tokens_est for r in measured]
    mean_out_tok = statistics.mean(out_tokens) if out_tokens else 0
    cost_per_q_usd = mean_out_tok / 1_000_000 * PRICE_OUTPUT_PER_1M_USD
    ws.append([])
    ws.append(["ต้นทุนโดยประมาณ (เฉพาะ output token)", "", "", "", "", "", ""])
    ws.append(["out_tokens_est เฉลี่ย/คำถาม", round(mean_out_tok, 1)])
    ws.append(["cost/คำถาม (USD)", round(cost_per_q_usd, 6)])
    ws.append(["cost/คำถาม (THB)", round(cost_per_q_usd * USD_TO_THB, 4)])
    n_err = len([r for r in results if not r.warmup and not r.ok])
    ws.append(["error count (measured)", n_err])
    style_header(ws, 7)
    ws.column_dimensions["A"].width = 36

    # --- LoadTest sheet ---
    if load_rows:
        ws = wb.create_sheet("LoadTest")
        ws.append(["concurrency", "requests", "ok", "errors", "wall_s",
                   "throughput_rps", "lat_mean", "lat_p50", "lat_p95", "lat_max"])
        for row in load_rows:
            ws.append([row["concurrency"], row["requests"], row["ok"], row["errors"],
                       row["wall_s"], row["throughput_rps"], row["lat_mean"],
                       row["lat_p50"], row["lat_p95"], row["lat_max"]])
        style_header(ws, 10)
        chart = BarChart()
        chart.title = "Throughput (req/s) ตามระดับ concurrency"
        chart.y_axis.title = "req/s"
        chart.x_axis.title = "concurrency"
        data = Reference(ws, min_col=6, min_row=1, max_row=ws.max_row)
        cats = Reference(ws, min_col=1, min_row=2, max_row=ws.max_row)
        chart.add_data(data, titles_from_data=True)
        chart.set_categories(cats)
        chart.height, chart.width = 9, 16
        ws.add_chart(chart, "K2")

    path = OUT_DIR / "perf_summary.xlsx"
    wb.save(path)
    return path


async def main() -> None:
    questions = load_questions()
    print(f"โหลดคำถาม {len(questions)} ข้อ | target = {BASE_URL + ENDPOINT}")
    limits = httpx.Limits(max_connections=max(LOAD_LEVELS) + 4 if RUN_LOAD_TEST else 8)
    async with httpx.AsyncClient(limits=limits) as client:
        # health check
        try:
            h = await client.get(BASE_URL + "/health", timeout=10)
            print(f"health: {h.status_code} {h.text.strip()}")
        except Exception as e:  # noqa: BLE001
            sys.exit(f"ต่อ backend ไม่ได้ที่ {BASE_URL} — เปิด server ก่อน ({e})")

        print("\n=== Sequential benchmark ===")
        results = await run_sequential(client, questions)

        load_rows: list[dict] = []
        if RUN_LOAD_TEST:
            print("\n=== Load test ===")
            for level in LOAD_LEVELS:
                row = await run_load(client, questions, level)
                load_rows.append(row)
                print(f"  concurrency={level:<2} -> {row['throughput_rps']} req/s | "
                      f"lat_mean={row['lat_mean']}s p95={row['lat_p95']}s err={row['errors']}")

    csv_path = write_csv(results)
    xlsx_path = write_xlsx(results, load_rows)
    print(f"\nเสร็จแล้ว:\n  {csv_path}\n  {xlsx_path}")


if __name__ == "__main__":
    asyncio.run(main())
