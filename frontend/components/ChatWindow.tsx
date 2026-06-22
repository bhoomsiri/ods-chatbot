"use client";

import { useEffect, useRef } from "react";
import ChatMessage from "./ChatMessage";
import ChatInput from "./ChatInput";
import { CATEGORIES, DEPARTMENTS } from "@/lib/types";
import type {
  Category,
  Department,
  ChatMessage as Message,
} from "@/lib/types";

const SUGGESTIONS = [
  "ก่อนผ่าตัดต้องงดน้ำงดอาหารกี่ชั่วโมง?",
  "หลังผ่าตัดดูแลแผลอย่างไร ห้ามโดนน้ำกี่วัน?",
  "ต้องเตรียมตัวและเอกสารอะไรมาบ้างในวันผ่าตัด?",
];

interface Props {
  messages: Message[];
  sending: boolean;
  category: Category;
  department: Department;
  onCategoryChange: (c: Category) => void;
  onDepartmentChange: (d: Department) => void;
  onSend: (text: string) => void;
  /** Open the history drawer (mobile only). */
  onOpenHistory: () => void;
  /** Open the sources drawer (mobile/tablet only). */
  onOpenSources: () => void;
}

function MenuIcon() {
  return (
    <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
      <path strokeLinecap="round" strokeLinejoin="round" d="M3.75 6.75h16.5M3.75 12h16.5m-16.5 5.25h16.5" />
    </svg>
  );
}

function DocIcon() {
  return (
    <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" strokeWidth={1.8} stroke="currentColor">
      <path
        strokeLinecap="round"
        strokeLinejoin="round"
        d="M19.5 14.25v-2.625a3.375 3.375 0 0 0-3.375-3.375h-1.5A1.125 1.125 0 0 1 13.5 7.125v-1.5a3.375 3.375 0 0 0-3.375-3.375H8.25m2.25 0H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 0 0-9-9Z"
      />
    </svg>
  );
}

export default function ChatWindow({
  messages,
  sending,
  category,
  department,
  onCategoryChange,
  onDepartmentChange,
  onSend,
  onOpenHistory,
  onOpenSources,
}: Props) {
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    scrollRef.current?.scrollTo({
      top: scrollRef.current.scrollHeight,
      behavior: "smooth",
    });
  }, [messages]);

  const empty = messages.length === 0;

  return (
    <section className="flex h-full flex-1 flex-col bg-slate-100">
      {/* Top bar: drawer toggles (mobile) + category/department filters */}
      <header className="flex items-center gap-2 border-b border-slate-200 bg-white px-3 py-2.5 sm:px-5 sm:py-3">
        <button
          type="button"
          onClick={onOpenHistory}
          className="rounded-lg p-1.5 text-slate-500 hover:bg-slate-100 hover:text-slate-700 md:hidden"
          title="ประวัติการสนทนา"
        >
          <MenuIcon />
        </button>
        <div className="ml-auto flex min-w-0 items-center gap-2 sm:gap-3">
          <div className="flex min-w-0 items-center gap-1.5">
            <label className="hidden text-xs font-medium text-slate-500 sm:inline">หมวดหมู่</label>
            <select
              value={category}
              onChange={(e) => onCategoryChange(e.target.value as Category)}
              className="min-w-0 max-w-[40vw] rounded-lg border border-slate-300 bg-white px-2 py-1.5 text-sm text-slate-700 outline-none focus:border-brand-400 focus:ring-2 focus:ring-brand-100 sm:max-w-none sm:px-2.5"
            >
              {CATEGORIES.map((c) => (
                <option key={c.value} value={c.value}>
                  {c.label}
                </option>
              ))}
            </select>
          </div>
          <div className="flex min-w-0 items-center gap-1.5">
            <label className="hidden text-xs font-medium text-slate-500 sm:inline">แผนก</label>
            <select
              value={department}
              onChange={(e) => onDepartmentChange(e.target.value as Department)}
              className="min-w-0 max-w-[40vw] rounded-lg border border-slate-300 bg-white px-2 py-1.5 text-sm text-slate-700 outline-none focus:border-brand-400 focus:ring-2 focus:ring-brand-100 sm:max-w-none sm:px-2.5"
            >
              {DEPARTMENTS.map((d) => (
                <option key={d.value} value={d.value}>
                  {d.label}
                </option>
              ))}
            </select>
          </div>
          <button
            type="button"
            onClick={onOpenSources}
            className="rounded-lg p-1.5 text-slate-500 hover:bg-slate-100 hover:text-slate-700 lg:hidden"
            title="แหล่งอ้างอิง"
          >
            <DocIcon />
          </button>
        </div>
      </header>

      <div ref={scrollRef} className="scroll-thin flex-1 overflow-y-auto">
        {empty ? (
          <div className="flex h-full flex-col items-center justify-center px-6 text-center">
            <div className="mb-4 flex h-14 w-14 items-center justify-center rounded-2xl bg-brand-600 text-lg font-bold text-white">
              ODS
            </div>
            <h2 className="text-xl font-semibold text-slate-800">
              สอบถามเรื่องการผ่าตัดแบบวันเดียวได้เลยครับ
            </h2>
            <p className="mt-2 max-w-md text-sm text-slate-500">
              ผู้ช่วยตอบจากคู่มือ One-Day Surgery ของโรงพยาบาลโพธาราม
              พร้อมอ้างอิงหน้าเอกสารทุกครั้ง
            </p>
            <div className="mt-6 flex flex-wrap justify-center gap-2">
              {SUGGESTIONS.map((s) => (
                <button
                  key={s}
                  onClick={() => onSend(s)}
                  className="rounded-full border border-slate-200 bg-white px-4 py-2 text-sm text-slate-600 shadow-sm transition-colors hover:border-brand-300 hover:bg-brand-50 hover:text-brand-700"
                >
                  {s}
                </button>
              ))}
            </div>
          </div>
        ) : (
          <div className="mx-auto max-w-3xl space-y-6 px-4 py-6">
            {messages.map((m) => (
              <ChatMessage key={m.id} message={m} />
            ))}
          </div>
        )}
      </div>

      <p className="bg-amber-50 px-4 py-1.5 text-center text-[11px] text-amber-700">
        ⚠️ ข้อมูลจากคู่มือเท่านั้น ไม่ใช่การวินิจฉัยทางการแพทย์ — หากมีอาการผิดปกติ
        กรุณาปรึกษาเจ้าหน้าที่หรือแพทย์
      </p>
      <ChatInput onSend={onSend} disabled={sending} />
    </section>
  );
}
