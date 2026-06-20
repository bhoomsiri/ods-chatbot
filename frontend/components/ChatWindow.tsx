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
}

export default function ChatWindow({
  messages,
  sending,
  category,
  department,
  onCategoryChange,
  onDepartmentChange,
  onSend,
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
      {/* Top bar: title (mobile) + category filter */}
      <header className="flex items-center justify-between gap-3 border-b border-slate-200 bg-white px-5 py-3">
        <div className="flex items-center gap-2 md:hidden">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-brand-600 text-xs font-bold text-white">
            ODS
          </div>
          <span className="text-sm font-semibold">ODS Chatbot</span>
        </div>
        <div className="ml-auto flex items-center gap-3">
          <div className="flex items-center gap-1.5">
            <label className="text-xs font-medium text-slate-500">หมวดหมู่</label>
            <select
              value={category}
              onChange={(e) => onCategoryChange(e.target.value as Category)}
              className="rounded-lg border border-slate-300 bg-white px-2.5 py-1.5 text-sm text-slate-700 outline-none focus:border-brand-400 focus:ring-2 focus:ring-brand-100"
            >
              {CATEGORIES.map((c) => (
                <option key={c.value} value={c.value}>
                  {c.label}
                </option>
              ))}
            </select>
          </div>
          <div className="flex items-center gap-1.5">
            <label className="text-xs font-medium text-slate-500">แผนก</label>
            <select
              value={department}
              onChange={(e) => onDepartmentChange(e.target.value as Department)}
              className="rounded-lg border border-slate-300 bg-white px-2.5 py-1.5 text-sm text-slate-700 outline-none focus:border-brand-400 focus:ring-2 focus:ring-brand-100"
            >
              {DEPARTMENTS.map((d) => (
                <option key={d.value} value={d.value}>
                  {d.label}
                </option>
              ))}
            </select>
          </div>
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
