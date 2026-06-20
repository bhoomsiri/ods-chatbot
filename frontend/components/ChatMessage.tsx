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
      id={`msg-${message.id}`}
      className={`flex animate-fade-in scroll-mt-4 gap-3 ${
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

        {/* Citations are shown in the left sources panel (CitationsPanel),
            Claude-style, not inline under each message. */}
      </div>
    </div>
  );
}
