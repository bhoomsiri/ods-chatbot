"use client";

import { useRef, useState } from "react";
import { ingestFiles } from "@/lib/api";
import type { IngestResult } from "@/lib/types";
import CitationsPanel from "./CitationsPanel";
import type { CitationGroup } from "./CitationsPanel";

export default function Sidebar({
  citationGroups = [],
}: {
  citationGroups?: CitationGroup[];
}) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const [results, setResults] = useState<IngestResult[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [dragOver, setDragOver] = useState(false);
  const [uploadOpen, setUploadOpen] = useState(false);

  async function handleFiles(fileList: FileList | null) {
    if (!fileList || fileList.length === 0) return;
    const files = Array.from(fileList);
    setBusy(true);
    setError(null);
    try {
      const res = await ingestFiles(files);
      setResults((prev) => [...res, ...prev]);
    } catch (e) {
      setError(e instanceof Error ? e.message : "อัปโหลดไม่สำเร็จ");
    } finally {
      setBusy(false);
      if (inputRef.current) inputRef.current.value = "";
    }
  }

  return (
    <aside className="hidden w-80 shrink-0 flex-col border-r border-slate-200 bg-white md:flex">
      <div className="flex items-center gap-3 border-b border-slate-200 px-5 py-4">
        <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-brand-600 text-sm font-bold text-white">
          ODS
        </div>
        <div>
          <h1 className="text-sm font-semibold text-slate-900">ODS Chatbot</h1>
          <p className="text-xs text-slate-500">โรงพยาบาลโพธาราม</p>
        </div>
      </div>

      {/* Main area: sources panel */}
      <div className="scroll-thin flex-1 overflow-y-auto">
        <CitationsPanel groups={citationGroups} />
      </div>

      {/* Bottom: collapsible knowledge-base upload */}
      <div className="border-t border-slate-200">
        <button
          type="button"
          onClick={() => setUploadOpen((o) => !o)}
          className="flex w-full items-center gap-2 px-5 py-3 text-xs font-semibold uppercase tracking-wide text-slate-500 hover:text-slate-700"
        >
          <svg
            className={`h-3.5 w-3.5 shrink-0 transition-transform ${uploadOpen ? "rotate-90" : ""}`}
            fill="none"
            viewBox="0 0 24 24"
            strokeWidth={2.5}
            stroke="currentColor"
          >
            <path strokeLinecap="round" strokeLinejoin="round" d="m8.25 4.5 7.5 7.5-7.5 7.5" />
          </svg>
          <span>เพิ่มเอกสารฐานความรู้</span>
        </button>

        {uploadOpen && (
          <div className="max-h-[60vh] overflow-y-auto px-5 pb-4">
            <div
              onDragOver={(e) => {
                e.preventDefault();
                setDragOver(true);
              }}
              onDragLeave={() => setDragOver(false)}
              onDrop={(e) => {
                e.preventDefault();
                setDragOver(false);
                handleFiles(e.dataTransfer.files);
              }}
              onClick={() => inputRef.current?.click()}
              className={`flex cursor-pointer flex-col items-center justify-center rounded-xl border-2 border-dashed px-4 py-6 text-center transition-colors ${
                dragOver
                  ? "border-brand-500 bg-brand-50"
                  : "border-slate-300 bg-slate-50 hover:border-brand-400 hover:bg-brand-50/50"
              }`}
            >
              <svg
                className="mb-2 h-7 w-7 text-slate-400"
                fill="none"
                viewBox="0 0 24 24"
                strokeWidth={1.5}
                stroke="currentColor"
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  d="M3 16.5v2.25A2.25 2.25 0 0 0 5.25 21h13.5A2.25 2.25 0 0 0 21 18.75V16.5m-13.5-9L12 3m0 0 4.5 4.5M12 3v13.5"
                />
              </svg>
              <p className="text-sm font-medium text-slate-700">
                ลากไฟล์มาวาง หรือคลิกเพื่อเลือก
              </p>
              <p className="mt-1 text-xs text-slate-400">PDF, DOCX, TXT, MD</p>
              <input
                ref={inputRef}
                type="file"
                multiple
                accept=".pdf,.docx,.txt,.md"
                className="hidden"
                onChange={(e) => handleFiles(e.target.files)}
              />
            </div>

            {busy && (
              <p className="mt-3 flex items-center gap-2 text-xs text-brand-600">
                <span className="h-3 w-3 animate-spin rounded-full border-2 border-brand-300 border-t-brand-600" />
                กำลังประมวลผลเอกสาร...
              </p>
            )}
            {error && (
              <p className="mt-3 rounded-lg bg-red-50 px-3 py-2 text-xs text-red-600">
                {error}
              </p>
            )}

            {results.length > 0 && (
              <div className="mt-4">
                <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">
                  เอกสารล่าสุด
                </h3>
                <ul className="space-y-2">
                  {results.map((r, i) => (
                    <li
                      key={`${r.filename}-${i}`}
                      className="flex items-start gap-2 rounded-lg border border-slate-200 bg-white px-3 py-2"
                    >
                      <span
                        className={`mt-1 h-2 w-2 shrink-0 rounded-full ${
                          r.status === "success" ? "bg-emerald-500" : "bg-red-500"
                        }`}
                      />
                      <div className="min-w-0">
                        <p className="truncate text-xs font-medium text-slate-700">
                          {r.filename}
                        </p>
                        <p className="text-[11px] text-slate-400">
                          {r.status === "success"
                            ? `${r.chunks ?? "?"} chunks`
                            : r.detail || "ผิดพลาด"}
                        </p>
                      </div>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        )}
      </div>

      <div className="border-t border-slate-200 px-5 py-3 text-[11px] text-slate-400">
        Powered by Qdrant · BGE-M3 · Gemini
      </div>
    </aside>
  );
}
