"use client";

import { useState } from "react";
import { type Identity, login, logout } from "@/lib/identity";
import type { ConversationSummary } from "@/lib/types";

interface Props {
  conversations: ConversationSummary[];
  activeId: string | null;
  identity: Identity | null;
  onNew: () => void;
  onSelect: (id: string) => void;
  onDelete: (id: string) => void;
  onRename: (id: string, title: string) => void;
}

function PlusIcon() {
  return (
    <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
      <path strokeLinecap="round" strokeLinejoin="round" d="M12 4.5v15m7.5-7.5h-15" />
    </svg>
  );
}

function LogoutIcon() {
  return (
    <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
      <path
        strokeLinecap="round"
        strokeLinejoin="round"
        d="M15.75 9V5.25A2.25 2.25 0 0 0 13.5 3h-6a2.25 2.25 0 0 0-2.25 2.25v13.5A2.25 2.25 0 0 0 7.5 21h6a2.25 2.25 0 0 0 2.25-2.25V15m3 0 3-3m0 0-3-3m3 3H9"
      />
    </svg>
  );
}

function TrashIcon() {
  return (
    <svg className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
      <path
        strokeLinecap="round"
        strokeLinejoin="round"
        d="m14.74 9-.346 9m-4.788 0L9.26 9m9.968-3.21c.342.052.682.107 1.022.166m-1.022-.165L18.16 19.673a2.25 2.25 0 0 1-2.244 2.077H8.084a2.25 2.25 0 0 1-2.244-2.077L4.772 5.79m14.456 0a48.108 48.108 0 0 0-3.478-.397m-12 .562c.34-.059.68-.114 1.022-.165m0 0a48.11 48.11 0 0 1 3.478-.397m7.5 0v-.916c0-1.18-.91-2.164-2.09-2.201a51.964 51.964 0 0 0-3.32 0c-1.18.037-2.09 1.022-2.09 2.201v.916m7.5 0a48.667 48.667 0 0 0-7.5 0"
      />
    </svg>
  );
}

function Row({
  conv,
  active,
  onSelect,
  onDelete,
  onRename,
}: {
  conv: ConversationSummary;
  active: boolean;
  onSelect: (id: string) => void;
  onDelete: (id: string) => void;
  onRename: (id: string, title: string) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(conv.title);

  function commit() {
    const t = draft.trim();
    setEditing(false);
    if (t && t !== conv.title) onRename(conv.id, t);
    else setDraft(conv.title);
  }

  return (
    <div
      className={`group flex items-center gap-1 rounded-lg px-2 py-2 text-sm transition-colors ${
        active ? "bg-brand-50 text-brand-800" : "text-slate-700 hover:bg-slate-100"
      }`}
    >
      {editing ? (
        <input
          autoFocus
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onBlur={commit}
          onKeyDown={(e) => {
            if (e.key === "Enter") commit();
            if (e.key === "Escape") {
              setDraft(conv.title);
              setEditing(false);
            }
          }}
          className="min-w-0 flex-1 rounded border border-brand-300 bg-white px-1.5 py-0.5 text-sm outline-none"
        />
      ) : (
        <button
          type="button"
          onClick={() => onSelect(conv.id)}
          onDoubleClick={() => {
            setDraft(conv.title);
            setEditing(true);
          }}
          className="min-w-0 flex-1 truncate text-left"
          title={conv.title}
        >
          {conv.title || "แชตใหม่"}
        </button>
      )}
      {!editing && (
        <button
          type="button"
          onClick={() => {
            if (confirm(`ลบแชต "${conv.title}" ?`)) onDelete(conv.id);
          }}
          className="shrink-0 rounded p-1 text-slate-400 opacity-0 transition hover:bg-slate-200 hover:text-red-600 group-hover:opacity-100"
          title="ลบแชต"
        >
          <TrashIcon />
        </button>
      )}
    </div>
  );
}

export default function HistorySidebar({
  conversations,
  activeId,
  identity,
  onNew,
  onSelect,
  onDelete,
  onRename,
}: Props) {
  return (
    <aside className="hidden w-72 shrink-0 flex-col border-r border-slate-200 bg-white md:flex">
      <div className="flex items-center gap-3 border-b border-slate-200 px-4 py-4">
        <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-brand-600 text-sm font-bold text-white">
          ODS
        </div>
        <div className="min-w-0">
          <h1 className="truncate text-sm font-semibold text-slate-900">ODS Chatbot</h1>
          <p className="truncate text-xs text-slate-500">โรงพยาบาลโพธาราม</p>
        </div>
      </div>

      <div className="px-3 py-3">
        <button
          type="button"
          onClick={onNew}
          className="flex w-full items-center justify-center gap-2 rounded-lg bg-brand-600 px-3 py-2 text-sm font-medium text-white shadow-sm transition-colors hover:bg-brand-700"
        >
          <PlusIcon />
          แชตใหม่
        </button>
      </div>

      <div className="scroll-thin flex-1 overflow-y-auto px-3 pb-3">
        <h2 className="px-2 pb-1 pt-2 text-xs font-semibold uppercase tracking-wide text-slate-400">
          ประวัติการสนทนา
        </h2>
        {conversations.length === 0 ? (
          <p className="px-2 py-3 text-xs text-slate-400">ยังไม่มีประวัติแชต</p>
        ) : (
          <div className="space-y-0.5">
            {conversations.map((c) => (
              <Row
                key={c.id}
                conv={c}
                active={c.id === activeId}
                onSelect={onSelect}
                onDelete={onDelete}
                onRename={onRename}
              />
            ))}
          </div>
        )}
      </div>

      {/* Bottom-left account area: who's signed in (via Cloudflare Access) +
         log out, or a log in button when no session is detected. */}
      <div className="border-t border-slate-200 p-3">
        {identity ? (
          <div className="flex items-center gap-2">
            <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-brand-100 text-xs font-semibold uppercase text-brand-700">
              {identity.email.charAt(0)}
            </div>
            <div className="min-w-0 flex-1">
              <p className="truncate text-xs font-medium text-slate-700" title={identity.email}>
                {identity.name || identity.email}
              </p>
              {identity.name && (
                <p className="truncate text-[11px] text-slate-400" title={identity.email}>
                  {identity.email}
                </p>
              )}
            </div>
            <button
              type="button"
              onClick={logout}
              title="ออกจากระบบ"
              className="shrink-0 rounded-lg p-2 text-slate-400 transition hover:bg-slate-100 hover:text-red-600"
            >
              <LogoutIcon />
            </button>
          </div>
        ) : (
          <button
            type="button"
            onClick={login}
            className="flex w-full items-center justify-center gap-2 rounded-lg border border-slate-300 px-3 py-2 text-sm font-medium text-slate-700 transition hover:bg-slate-50"
          >
            <LogoutIcon />
            เข้าสู่ระบบ
          </button>
        )}
      </div>
    </aside>
  );
}
