export type Role = "user" | "assistant";

/**
 * Content category — matches the `category` tag stored on each chunk in Qdrant.
 * "all" means no filter (omitted from the request).
 */
export type Category =
  | "all"
  | "ความรู้พื้นฐาน"
  | "ก่อนผ่าตัด"
  | "หลังผ่าตัด"
  | "เทคนิค";

/**
 * Surgical department — matches the `department` tag stored on each chunk in the
 * active collection (v3). GI endoscopy was folded into ศัลยกรรมทั่วไป, so there
 * is no separate scope department.
 */
export type Department =
  | "all"
  | "ศัลยกรรมทั่วไป"
  | "จักษุ"
  | "โสต ศอ นาสิก"
  | "นรีเวช"
  | "หลอดเลือด";

export interface CategoryOption {
  value: Category;
  label: string;
}

export interface DepartmentOption {
  value: Department;
  label: string;
}

export const CATEGORIES: CategoryOption[] = [
  { value: "all", label: "ทุกหมวด" },
  { value: "ความรู้พื้นฐาน", label: "ความรู้พื้นฐาน" },
  { value: "ก่อนผ่าตัด", label: "ก่อนผ่าตัด" },
  { value: "หลังผ่าตัด", label: "หลังผ่าตัด" },
  { value: "เทคนิค", label: "เทคนิค/การแพทย์" },
];

export const DEPARTMENTS: DepartmentOption[] = [
  { value: "all", label: "ทุกแผนก" },
  { value: "ศัลยกรรมทั่วไป", label: "ศัลยกรรมทั่วไป" },
  { value: "จักษุ", label: "จักษุ" },
  { value: "โสต ศอ นาสิก", label: "หู คอ จมูก" },
  { value: "นรีเวช", label: "นรีเวช" },
  { value: "หลอดเลือด", label: "หลอดเลือด" },
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
  /** Existing thread to append to. Omitted starts a new conversation. */
  conversationId?: string;
  /** Tag filters. Omitted means no filter on that dimension. */
  category?: string;
  department?: string;
}

export interface ChatResponse {
  answer: string;
  citations?: Citation[];
}

/** A chat thread shown in the left history sidebar. */
export interface ConversationSummary {
  id: string;
  title: string;
  updatedAt?: string;
}

/** A full conversation with its messages (for loading from history). */
export interface ConversationDetail {
  id: string;
  title: string;
  messages: ChatMessage[];
}

/**
 * Server-sent event shape the frontend expects from POST /api/chat
 * (text/event-stream). The backend may also return a plain JSON ChatResponse,
 * which the client handles as a non-streaming fallback.
 */
export type ChatStreamEvent =
  | { type: "conversation"; id: string; title: string }
  | { type: "token"; text: string }
  | { type: "citations"; citations: Citation[] }
  | { type: "done" }
  | { type: "error"; detail: string };

export interface ChatStreamHandlers {
  onToken: (text: string) => void;
  onCitations: (citations: Citation[]) => void;
  /** Fired once the server resolves/creates the thread for this message. */
  onConversation?: (conv: { id: string; title: string }) => void;
  signal?: AbortSignal;
}

export interface IngestResult {
  filename: string;
  status: "success" | "error";
  chunks?: number;
  detail?: string;
}
