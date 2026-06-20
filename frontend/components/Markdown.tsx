"use client";

import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

/**
 * Renders an assistant message as Markdown. Gemini answers use **bold**,
 * `*`/`-` bullet lists, numbered lists and paragraphs; without this they show
 * as raw asterisks. Styled to match the chat bubble (small, tight spacing).
 * react-markdown tolerates incomplete markdown during streaming (e.g. an
 * unclosed `**` stays plain text until the closing tokens arrive).
 */
export default function Markdown({ children }: { children: string }) {
  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm]}
      components={{
        p: ({ children }) => <p className="mb-2 last:mb-0">{children}</p>,
        ul: ({ children }) => (
          <ul className="mb-2 list-disc space-y-1 pl-5 last:mb-0">{children}</ul>
        ),
        ol: ({ children }) => (
          <ol className="mb-2 list-decimal space-y-1 pl-5 last:mb-0">{children}</ol>
        ),
        li: ({ children }) => <li className="leading-relaxed">{children}</li>,
        strong: ({ children }) => (
          <strong className="font-semibold">{children}</strong>
        ),
        em: ({ children }) => <em className="italic">{children}</em>,
        a: ({ href, children }) => (
          <a
            href={href}
            target="_blank"
            rel="noreferrer"
            className="text-brand-600 underline underline-offset-2"
          >
            {children}
          </a>
        ),
        h1: ({ children }) => (
          <h3 className="mb-1 mt-2 font-semibold first:mt-0">{children}</h3>
        ),
        h2: ({ children }) => (
          <h3 className="mb-1 mt-2 font-semibold first:mt-0">{children}</h3>
        ),
        h3: ({ children }) => (
          <h3 className="mb-1 mt-2 font-semibold first:mt-0">{children}</h3>
        ),
        code: ({ children }) => (
          <code className="rounded bg-slate-100 px-1 py-0.5 text-[0.85em]">
            {children}
          </code>
        ),
      }}
    >
      {children}
    </ReactMarkdown>
  );
}
