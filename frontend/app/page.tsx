"use client";

import { useEffect, useState } from "react";
import ChatWindow from "@/components/ChatWindow";
import HistorySidebar from "@/components/HistorySidebar";
import LoginScreen from "@/components/LoginScreen";
import SourcesPanel from "@/components/SourcesPanel";
import {
  deleteConversation,
  getConversation,
  listConversations,
  renameConversation,
  streamChat,
} from "@/lib/api";
import { ENTERED_KEY, type Identity, fetchIdentity, login } from "@/lib/identity";
import type {
  Category,
  ConversationSummary,
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
  const [conversations, setConversations] = useState<ConversationSummary[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [identity, setIdentity] = useState<Identity | null>(null);
  // Login screen shows first when opening the app, but a plain refresh keeps you
  // in: the flag lives in sessionStorage (survives refresh, cleared when the tab
  // /browser closes). `checked` gates the first paint so we don't flash the
  // login screen before reading sessionStorage. Real auth is enforced by
  // Cloudflare Access upstream; this is the in-app entry step.
  const [entered, setEntered] = useState(false);
  const [checked, setChecked] = useState(false);
  // Mobile drawer state (sidebars are static on desktop).
  const [historyOpen, setHistoryOpen] = useState(false);
  const [sourcesOpen, setSourcesOpen] = useState(false);

  // Load the history list once on mount (scoped to this browser's client id).
  useEffect(() => {
    listConversations()
      .then(setConversations)
      .catch(() => setConversations([]));
  }, []);

  // Resolve who's signed in via Cloudflare Access (null off-Cloudflare / dev).
  useEffect(() => {
    fetchIdentity().then(setIdentity).catch(() => {});
  }, []);

  // After mount, restore the "entered" flag so a refresh skips the login screen.
  useEffect(() => {
    try {
      if (window.sessionStorage.getItem(ENTERED_KEY) === "1") setEntered(true);
    } catch {
      /* sessionStorage unavailable — ignore */
    }
    setChecked(true);
  }, []);

  function handleNewChat() {
    setActiveId(null);
    setMessages([]);
    setHistoryOpen(false); // close the drawer on mobile after acting
  }

  async function handleSelect(id: string) {
    setHistoryOpen(false); // close the drawer on mobile after picking
    if (id === activeId) return;
    try {
      const detail = await getConversation(id);
      setActiveId(id);
      setMessages(detail.messages);
    } catch {
      // Stale entry (deleted elsewhere) — drop it and reset.
      setConversations((prev) => prev.filter((c) => c.id !== id));
      handleNewChat();
    }
  }

  async function handleDelete(id: string) {
    try {
      await deleteConversation(id);
    } catch {
      /* ignore — remove locally regardless */
    }
    setConversations((prev) => prev.filter((c) => c.id !== id));
    if (id === activeId) handleNewChat();
  }

  async function handleRename(id: string, title: string) {
    setConversations((prev) =>
      prev.map((c) => (c.id === id ? { ...c, title } : c)),
    );
    try {
      await renameConversation(id, title);
    } catch {
      // Revert on failure by reloading the authoritative list.
      listConversations().then(setConversations).catch(() => {});
    }
  }

  /** Insert/refresh a conversation at the top of the sidebar. */
  function upsertConversation(id: string, title: string) {
    setConversations((prev) => {
      const existing = prev.find((c) => c.id === id);
      const rest = prev.filter((c) => c.id !== id);
      return [{ id, title: existing?.title ?? title }, ...rest];
    });
  }

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
          conversationId: activeId ?? undefined,
          category: category === "all" ? undefined : category,
          department: department === "all" ? undefined : department,
        },
        {
          onConversation: ({ id, title }) => {
            setActiveId(id);
            upsertConversation(id, title);
          },
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

  // Right panel: one group per answered question (Claude-style hierarchy),
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

  // Entering the chat from the login screen. If Cloudflare already signed the
  // user in (or we're on localhost with no gateway), proceed; otherwise on a
  // real deploy with no session, send them to the Cloudflare Google login.
  function handleEnter() {
    const host = window.location.hostname;
    const isLocal = host === "localhost" || host === "127.0.0.1";
    if (identity || isLocal) {
      try {
        window.sessionStorage.setItem(ENTERED_KEY, "1");
      } catch {
        /* sessionStorage unavailable — ignore */
      }
      setEntered(true);
    } else {
      login();
    }
  }

  // Hold the first paint until we've read sessionStorage (avoids flashing the
  // login screen on a refresh that should stay in the chat).
  if (!checked) return <main className="h-dvh w-full bg-slate-100" />;

  // Login screen when opening fresh; a refresh restores `entered` above.
  if (!entered) {
    return <LoginScreen identity={identity} onContinue={handleEnter} />;
  }

  return (
    <main className="flex h-dvh w-full overflow-hidden bg-slate-100">
      <HistorySidebar
        conversations={conversations}
        activeId={activeId}
        identity={identity}
        open={historyOpen}
        onClose={() => setHistoryOpen(false)}
        onNew={handleNewChat}
        onSelect={handleSelect}
        onDelete={handleDelete}
        onRename={handleRename}
      />
      <ChatWindow
        messages={messages}
        sending={sending}
        category={category}
        department={department}
        onCategoryChange={setCategory}
        onDepartmentChange={setDepartment}
        onSend={handleSend}
        onOpenHistory={() => setHistoryOpen(true)}
        onOpenSources={() => setSourcesOpen(true)}
      />
      <SourcesPanel
        citationGroups={citationGroups}
        open={sourcesOpen}
        onClose={() => setSourcesOpen(false)}
      />
    </main>
  );
}
