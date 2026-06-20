export type Role = "user" | "assistant";

/** Care phase used as the retrieval category filter (sent to the backend). */
export type Category = "all" | "pre_op" | "day_of" | "post_op" | "general";

export interface CategoryOption {
  value: Category;
  label: string;
}

export const CATEGORIES: CategoryOption[] = [
  { value: "all", label: "ทั้งหมด" },
  { value: "pre_op", label: "ก่อนผ่าตัด" },
  { value: "day_of", label: "วันผ่าตัด" },
  { value: "post_op", label: "หลังผ่าตัด" },
  { value: "general", label: "ทั่วไป" },
];

export interface Citation {
  id: string;
  /** Source document, e.g. "ODS MIS 2565". */
  source: string;
  page?: number | null;
  score?: number | null;
  snippet?: string;
  /** Optional rendered image of the cited page. */
  image?: string | null;
}

export interface ChatMessage {
  id: string;
  role: Role;
  content: string;
  citations?: Citation[];
  createdAt: number;
  /** True while the assistant answer is still being streamed. */
  pending?: boolean;
  /** Set when the request failed. */
  error?: string;
}

export interface ChatRequest {
  message: string;
  history?: { role: Role; content: string }[];
  /** Care-phase filter. Omitted/"all" means no category filter. */
  category?: Category;
}

export interface ChatResponse {
  answer: string;
  citations?: Citation[];
}

/**
 * Server-sent event shape the frontend expects from POST /api/chat
 * (text/event-stream). The backend may also return a plain JSON ChatResponse,
 * which the client handles as a non-streaming fallback.
 */
export type ChatStreamEvent =
  | { type: "token"; text: string }
  | { type: "citations"; citations: Citation[] }
  | { type: "done" }
  | { type: "error"; detail: string };

export interface ChatStreamHandlers {
  onToken: (text: string) => void;
  onCitations: (citations: Citation[]) => void;
  signal?: AbortSignal;
}

export interface IngestResult {
  filename: string;
  status: "success" | "error";
  chunks?: number;
  detail?: string;
}
