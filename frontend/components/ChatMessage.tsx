"use client";

import type { ChatMessage as Message } from "@/lib/types";
import Markdown from "@/components/Markdown";

function TypingDots() {
  return (
    <span className="inline-flex items-center gap-1">
      {[0, 1, 2].map((i) => (
        <span
          key={i}
          className="h-2 w-2 rounded-full bg-slate-400 animate-bounce-dot"
          style={{ animationDelay: `${i * 0.15}s` }}
        />
      ))}
    </span>
  );
}

export default function ChatMessage({ message }: { message: Message }) {
  const isUser = message.role === "user";

  return (
    <div
      className={`flex animate-fade-in gap-3 ${
        isUser ? "flex-row-reverse" : "flex-row"
      }`}
    >
      <div
        className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-xs font-semibold ${
          isUser ? "bg-slate-700 text-white" : "bg-brand-600 text-white"
        }`}
      >
        {isUser ? "คุณ" : "AI"}
      </div>

      <div className={`max-w-[78%] ${isUser ? "items-end" : "items-start"}`}>
        <div
          className={`rounded-2xl px-4 py-3 text-sm leading-relaxed shadow-sm ${
            isUser
              ? "rounded-tr-sm bg-brand-600 text-white"
              : message.error
                ? "rounded-tl-sm bg-red-50 text-red-700"
                : "rounded-tl-sm bg-white text-slate-800"
          }`}
        >
          {message.pending && !message.content ? (
            <TypingDots />
          ) : isUser ? (
            <span className="whitespace-pre-wrap">{message.content}</span>
          ) : message.content ? (
            <Markdown>{message.content}</Markdown>
          ) : (
            <span className="whitespace-pre-wrap">{message.error}</span>
          )}
        </div>

        {message.citations && message.citations.length > 0 && (
          <div className="mt-2 space-y-1.5">
            <p className="text-[11px] font-semibold uppercase tracking-wide text-slate-400">
              แหล่งอ้างอิง
            </p>
            {message.citations.map((c, i) => (
              <details
                key={c.id}
                className="group rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs"
              >
                <summary className="flex cursor-pointer list-none items-center gap-2 text-slate-600">
                  <span className="flex h-4 w-4 items-center justify-center rounded bg-brand-100 text-[10px] font-bold text-brand-700">
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
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
