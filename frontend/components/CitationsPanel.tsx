"use client";

import { useState } from "react";
import type { Citation } from "@/lib/types";

export interface CitationGroup {
  id: string;
  /** DOM id (msg-<id>) of the user question, for click-to-scroll. */
  questionId: string;
  question: string;
  citations: Citation[];
}

function Chevron({ open }: { open: boolean }) {
  return (
    <svg
      className={`h-3.5 w-3.5 shrink-0 transition-transform ${open ? "rotate-90" : ""}`}
      fill="none"
      viewBox="0 0 24 24"
      strokeWidth={2.5}
      stroke="currentColor"
    >
      <path strokeLinecap="round" strokeLinejoin="round" d="m8.25 4.5 7.5 7.5-7.5 7.5" />
    </svg>
  );
}

function SourceItem({ c, i }: { c: Citation; i: number }) {
  return (
    <details className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs">
      <summary className="flex cursor-pointer list-none items-center gap-2 text-slate-600">
        <span className="flex h-4 w-4 shrink-0 items-center justify-center rounded bg-brand-100 text-[10px] font-bold text-brand-700">
          {i + 1}
        </span>
        <span className="truncate font-medium text-slate-700">
          {c.source}
          {c.page != null ? ` หน้า ${c.page}` : ""}
        </span>
        {c.score != null && (
          <span className="ml-auto shrink-0 rounded bg-slate-100 px-1.5 py-0.5 text-[10px] text-slate-500">
            {(c.score * 100).toFixed(0)}%
          </span>
        )}
      </summary>
      {c.snippet && (
        <p className="mt-2 border-l-2 border-slate-200 pl-3 text-slate-500">
          {c.snippet}
        </p>
      )}
      {c.image && (
        // eslint-disable-next-line @next/next/no-img-element
        <img
          src={c.image}
          alt={`${c.source} หน้า ${c.page ?? ""}`}
          className="mt-2 max-h-56 w-full rounded-md border border-slate-200 object-contain"
        />
      )}
    </details>
  );
}

/**
 * Collapsible sources panel (Claude-style), 3 levels:
 *   แหล่งอ้างอิง  ›  คำถาม (ต่อข้อ)  ›  แหล่งอ้างอิงของคำถามนั้น
 * The newest question is expanded by default.
 */
export default function CitationsPanel({ groups }: { groups: CitationGroup[] }) {
  const [open, setOpen] = useState(true);
  if (groups.length === 0) return null;

  const total = groups.reduce((n, g) => n + g.citations.length, 0);
  const newestId = groups[groups.length - 1]?.id;

  return (
    <div className="border-t border-slate-200 px-5 py-4">
      {/* Level 1: แหล่งอ้างอิง */}
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center gap-2 text-xs font-semibold uppercase tracking-wide text-slate-500 hover:text-slate-700"
      >
        <Chevron open={open} />
        <span>แหล่งอ้างอิง</span>
        <span className="ml-auto rounded-full bg-brand-100 px-2 py-0.5 text-[10px] font-bold text-brand-700">
          {total}
        </span>
      </button>

      {open && (
        <div className="mt-3 space-y-2">
          {/* Level 2: คำถาม (one collapsible group per question) */}
          {groups.map((g) => (
            <details
              key={g.id}
              open={g.id === newestId}
              className="group rounded-lg border border-slate-200 bg-slate-50"
            >
              <summary
                onClick={() => {
                  document
                    .getElementById(`msg-${g.questionId}`)
                    ?.scrollIntoView({ behavior: "smooth", block: "start" });
                }}
                className="flex cursor-pointer list-none items-center gap-2 px-3 py-2 text-xs"
              >
                <svg
                  className="h-3.5 w-3.5 shrink-0 text-slate-400 transition-transform group-open:rotate-90"
                  fill="none"
                  viewBox="0 0 24 24"
                  strokeWidth={2.5}
                  stroke="currentColor"
                >
                  <path strokeLinecap="round" strokeLinejoin="round" d="m8.25 4.5 7.5 7.5-7.5 7.5" />
                </svg>
                <span className="truncate font-medium text-slate-700" title={g.question}>
                  {g.question || "คำถาม"}
                </span>
                <span className="ml-auto shrink-0 rounded-full bg-slate-200 px-1.5 py-0.5 text-[10px] font-semibold text-slate-600">
                  {g.citations.length}
                </span>
              </summary>

              {/* Level 3: แหล่งอ้างอิงของคำถามนั้น */}
              <div className="space-y-1.5 px-2 pb-2">
                {g.citations.map((c, i) => (
                  <SourceItem key={c.id} c={c} i={i} />
                ))}
              </div>
            </details>
          ))}
        </div>
      )}
    </div>
  );
}
