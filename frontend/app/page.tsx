"use client";

import { useState } from "react";
import ChatWindow from "@/components/ChatWindow";
import Sidebar from "@/components/Sidebar";
import { streamChat } from "@/lib/api";
import type {
  Category,
  Department,
  ChatMessage as Message,
} from "@/lib/types";

let idCounter = 0;
const nextId = () => `m${Date.now()}-${idCounter++}`;

export default function Home() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [sending, setSending] = useState(false);
  const [category, setCategory] = useState<Category>("all");
  const [department, setDepartment] = useState<Department>("all");

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
          department: department === "all" ? undefined : department,
        },
        {
          onToken: (t) => patch((m) => ({ ...m, content: m.content + t })),
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

  // Sources panel: one group per answered question (Claude-style hierarchy),
  // pairing each cited assistant message with the user question before it.
  const citationGroups = messages.flatMap((m, i) =>
    m.role === "assistant" && (m.citations?.length ?? 0) > 0
      ? [
          {
            id: m.id,
            questionId: messages[i - 1]?.role === "user" ? messages[i - 1].id : m.id,
            question: messages[i - 1]?.role === "user" ? messages[i - 1].content : "",
            citations: m.citations ?? [],
          },
        ]
      : [],
  );

  return (
    <main className="flex h-screen w-full overflow-hidden bg-slate-100">
      <Sidebar citationGroups={citationGroups} />
      <ChatWindow
        messages={messages}
        sending={sending}
        category={category}
        department={department}
        onCategoryChange={setCategory}
        onDepartmentChange={setDepartment}
        onSend={handleSend}
      />
    </main>
  );
}
