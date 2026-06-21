import type {
  ChatMessage,
  ChatRequest,
  ChatStreamEvent,
  ChatStreamHandlers,
  Citation,
  ConversationDetail,
  ConversationSummary,
  IngestResult,
} from "./types";

/**
 * Base path for the API. Requests go to /api/* which next.config.js rewrites
 * to the FastAPI backend. Set NEXT_PUBLIC_API_BASE to override.
 */
const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "/api";

/** When true, the UI works without a backend by streaming canned replies. */
const USE_MOCK = process.env.NEXT_PUBLIC_USE_MOCK === "1";

function sleep(ms: number) {
  return new Promise((r) => setTimeout(r, ms));
}

/**
 * Stable per-browser identity sent as X-Client-Id so the backend can scope
 * conversations to "this browser" until Clerk auth lands (then the Clerk user
 * id takes over server-side, with no frontend change to the contract).
 */
function clientId(): string {
  if (typeof window === "undefined") return "anonymous";
  const KEY = "ods-client-id";
  let id = window.localStorage.getItem(KEY);
  if (!id) {
    id =
      typeof crypto !== "undefined" && "randomUUID" in crypto
        ? crypto.randomUUID()
        : `c-${Date.now()}-${Math.random().toString(36).slice(2)}`;
    window.localStorage.setItem(KEY, id);
  }
  return id;
}

function authHeaders(extra: Record<string, string> = {}): Record<string, string> {
  return { "X-Client-Id": clientId(), ...extra };
}

/** Admin key (for knowledge-base ingest), stored once in the admin's browser. */
export function getAdminKey(): string {
  if (typeof window === "undefined") return "";
  return window.localStorage.getItem("ods-admin-key") ?? "";
}

export function setAdminKey(key: string): void {
  if (typeof window === "undefined") return;
  if (key) window.localStorage.setItem("ods-admin-key", key);
  else window.localStorage.removeItem("ods-admin-key");
}

const MOCK_CITATIONS: Citation[] = [
  {
    id: "c1",
    source: "ODS MIS 2565",
    page: 12,
    score: 0.91,
    snippet:
      "ก่อนผ่าตัดต้องงดน้ำงดอาหาร (NPO) อย่างน้อย 6-8 ชั่วโมง เพื่อความปลอดภัยระหว่างการให้ยาระงับความรู้สึก...",
    image: null,
  },
  {
    id: "c2",
    source: "คู่มือผู้ป่วย ODS",
    page: 24,
    score: 0.83,
    snippet:
      "หลังผ่าตัด ห้ามให้แผลโดนน้ำเป็นเวลา 7 วัน สังเกตอาการบวมแดง มีหนอง หรือไข้ ให้รีบกลับมาพบแพทย์...",
    image: null,
  },
];

async function* mockTokens(req: ChatRequest): AsyncGenerator<string> {
  const answer =
    `(ตัวอย่าง/mock) สำหรับคำถาม: “${req.message}”\n\n` +
    "เมื่อต่อกับ backend จริง คำตอบจะดึงจากคู่มือ ODS ที่ถูก ingest เข้า Qdrant " +
    "พร้อมอ้างอิงหน้าเอกสารด้านล่าง โปรดทราบว่าระบบนี้ให้ข้อมูลจากคู่มือเท่านั้น " +
    "ไม่ใช่การวินิจฉัย หากมีอาการผิดปกติกรุณาปรึกษาเจ้าหน้าที่";
  for (const word of answer.split(/(\s+)/)) {
    await sleep(18);
    yield word;
  }
}

/**
 * Stream a chat answer. Calls onToken for each delta and onCitations when the
 * source list arrives. Resolves when the stream completes.
 */
export async function streamChat(
  req: ChatRequest,
  handlers: ChatStreamHandlers,
): Promise<void> {
  if (USE_MOCK) {
    for await (const t of mockTokens(req)) {
      if (handlers.signal?.aborted) return;
      handlers.onToken(t);
    }
    await sleep(150);
    handlers.onCitations(MOCK_CITATIONS);
    return;
  }

  const res = await fetch(`${API_BASE}/chat`, {
    method: "POST",
    headers: authHeaders({
      "Content-Type": "application/json",
      Accept: "text/event-stream",
    }),
    body: JSON.stringify({
      message: req.message,
      history: req.history,
      conversation_id: req.conversationId,
      category: req.category,
      department: req.department,
    }),
    signal: handlers.signal,
  });

  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(
      `Chat request failed (${res.status}). ${text || "ตรวจสอบว่า backend ทำงานอยู่หรือไม่"}`,
    );
  }

  const contentType = res.headers.get("content-type") ?? "";

  // Non-streaming fallback: a plain JSON ChatResponse.
  if (!contentType.includes("text/event-stream")) {
    const data = await res.json();
    if (typeof data?.answer === "string") handlers.onToken(data.answer);
    if (Array.isArray(data?.citations)) handlers.onCitations(data.citations);
    return;
  }

  if (!res.body) throw new Error("Response has no body to stream.");

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  const handleEvent = (raw: string) => {
    // Each SSE block: one or more "data: ..." lines.
    const dataLines = raw
      .split("\n")
      .filter((l) => l.startsWith("data:"))
      .map((l) => l.slice(5).trim());
    if (dataLines.length === 0) return;
    const payload = dataLines.join("\n");
    if (payload === "[DONE]") return;

    let evt: ChatStreamEvent;
    try {
      evt = JSON.parse(payload) as ChatStreamEvent;
    } catch {
      // Not JSON — tolerate servers that stream raw text deltas.
      handlers.onToken(payload);
      return;
    }
    // Parsed cleanly: handle the typed event. An error event must propagate
    // (so the caller marks the message failed) — not be swallowed and rendered
    // as answer text.
    if (evt.type === "token") handlers.onToken(evt.text);
    else if (evt.type === "citations") handlers.onCitations(evt.citations);
    else if (evt.type === "conversation")
      handlers.onConversation?.({ id: evt.id, title: evt.title });
    else if (evt.type === "error") throw new Error(evt.detail);
  };

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let sep: number;
    while ((sep = buffer.indexOf("\n\n")) !== -1) {
      handleEvent(buffer.slice(0, sep));
      buffer = buffer.slice(sep + 2);
    }
  }
  if (buffer.trim()) handleEvent(buffer);
}

export async function ingestFiles(files: File[]): Promise<IngestResult[]> {
  if (USE_MOCK) {
    await sleep(900);
    return files.map((f) => ({
      filename: f.name,
      status: "success" as const,
      chunks: Math.max(1, Math.round(f.size / 1200)),
    }));
  }

  const form = new FormData();
  files.forEach((f) => form.append("files", f));

  const adminKey = getAdminKey();
  const res = await fetch(`${API_BASE}/ingest`, {
    method: "POST",
    headers: authHeaders(adminKey ? { "X-Admin-Key": adminKey } : {}),
    body: form,
  });

  if (res.status === 403) {
    throw new Error("ต้องมีสิทธิ์ผู้ดูแล (admin key) จึงจะอัปโหลดเอกสารได้");
  }
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(
      `Ingest failed (${res.status}). ${text || "ตรวจสอบ endpoint /api/ingest"}`,
    );
  }

  const data = await res.json();
  if (Array.isArray(data)) return data as IngestResult[];
  if (Array.isArray(data?.results)) return data.results as IngestResult[];
  return files.map((f) => ({ filename: f.name, status: "success" as const }));
}

// --- Conversation history -------------------------------------------------

interface ApiCitation {
  id: string;
  source: string;
  page?: number | null;
  score?: number | null;
  snippet?: string | null;
  image?: string | null;
}

interface ApiMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  created_at: string;
  citations?: ApiCitation[];
}

function mapCitations(cs?: ApiCitation[]): Citation[] {
  return (cs ?? []).map((c) => ({
    id: c.id,
    source: c.source,
    page: c.page ?? null,
    score: c.score ?? null,
    snippet: c.snippet ?? undefined,
    image: c.image ?? null,
  }));
}

export async function listConversations(): Promise<ConversationSummary[]> {
  if (USE_MOCK) return [];
  const res = await fetch(`${API_BASE}/conversations`, { headers: authHeaders() });
  if (!res.ok) throw new Error(`โหลดประวัติแชตไม่สำเร็จ (${res.status})`);
  const data = (await res.json()) as Array<{
    id: string;
    title: string;
    updated_at: string;
  }>;
  return data.map((c) => ({ id: c.id, title: c.title, updatedAt: c.updated_at }));
}

export async function getConversation(id: string): Promise<ConversationDetail> {
  const res = await fetch(`${API_BASE}/conversations/${id}`, {
    headers: authHeaders(),
  });
  if (!res.ok) throw new Error(`เปิดแชตไม่สำเร็จ (${res.status})`);
  const data = (await res.json()) as {
    id: string;
    title: string;
    messages: ApiMessage[];
  };
  const messages: ChatMessage[] = data.messages.map((m) => ({
    id: m.id,
    role: m.role,
    content: m.content,
    createdAt: Date.parse(m.created_at) || Date.now(),
    citations: m.role === "assistant" ? mapCitations(m.citations) : undefined,
  }));
  return { id: data.id, title: data.title, messages };
}

export async function deleteConversation(id: string): Promise<void> {
  const res = await fetch(`${API_BASE}/conversations/${id}`, {
    method: "DELETE",
    headers: authHeaders(),
  });
  if (!res.ok && res.status !== 404)
    throw new Error(`ลบแชตไม่สำเร็จ (${res.status})`);
}

export async function renameConversation(
  id: string,
  title: string,
): Promise<void> {
  const res = await fetch(`${API_BASE}/conversations/${id}`, {
    method: "PATCH",
    headers: authHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify({ title }),
  });
  if (!res.ok) throw new Error(`เปลี่ยนชื่อแชตไม่สำเร็จ (${res.status})`);
}
