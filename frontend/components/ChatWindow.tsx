"use client";

import { useEffect, useRef, useState } from "react";
import ChatMessage from "./ChatMessage";
import ChatInput from "./ChatInput";
import { streamChat } from "@/lib/api";
import { CATEGORIES } from "@/lib/types";
import type { Category, ChatMessage as Message } from "@/lib/types";

const SUGGESTIONS = [
  "ก่อนผ่าตัดต้องงดน้ำงดอาหารกี่ชั่วโมง?",
  "หลังผ่าตัดดูแลแผลอย่างไร ห้ามโดนน้ำกี่วัน?",
  "ต้องเตรียมตัวและเอกสารอะไรมาบ้างในวันผ่าตัด?",
];

let idCounter = 0;
const nextId = () => `m${Date.now()}-${idCounter++}`;

export default function ChatWindow() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [sending, setSending] = useState(false);
  const [category, setCategory] = useState<Category>("all");
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    scrollRef.current?.scrollTo({
      top: scrollRef.current.scrollHeight,
      behavior: "smooth",
    });
  }, [messages]);

  async function handleSend(text: string) {
    const userMsg: Message = {
      id: nextId(),
      role: "user",
      content: text,
      createdAt: Date.now(),
    };
    const pendingId = nextId();
    const pendingMsg: Message = {
      id: pendingId,
      role: "assistant",
      content: "",
      createdAt: Date.now(),
      pending: true,
    };

    const history = messages.map((m) => ({ role: m.role, content: m.content }));
    setMessages((prev) => [...prev, userMsg, pendingMsg]);
    setSending(true);

    const patch = (fn: (m: Message) => Message) =>
      setMessages((prev) => prev.map((m) => (m.id === pendingId ? fn(m) : m)));

    try {
      await streamChat(
        {
          message: text,
          history,
          category: category === "all" ? undefined : category,
        },
        {
          onToken: (t) =>
            patch((m) => ({ ...m, content: m.content + t })),
          onCitations: (citations) => patch((m) => ({ ...m, citations })),
        },
      );
      patch((m) => ({ ...m, pending: false }));
    } catch (e) {
      patch((m) => ({
        ...m,
        pending: false,
        error: e instanceof Error ? e.message : "เกิดข้อผิดพลาดในการตอบกลับ",
      }));
    } finally {
      setSending(false);
    }
  }

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
        <div className="ml-auto flex items-center gap-2">
          <label className="text-xs font-medium text-slate-500">หมวดหมู่</label>
          <select
            value={category}
            onChange={(e) => setCategory(e.target.value as Category)}
            className="rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-sm text-slate-700 outline-none focus:border-brand-400 focus:ring-2 focus:ring-brand-100"
          >
            {CATEGORIES.map((c) => (
              <option key={c.value} value={c.value}>
                {c.label}
              </option>
            ))}
          </select>
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
                  onClick={() => handleSend(s)}
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
      <ChatInput onSend={handleSend} disabled={sending} />
    </section>
  );
}
