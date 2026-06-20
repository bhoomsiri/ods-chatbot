import type {
  ChatRequest,
  ChatStreamEvent,
  ChatStreamHandlers,
  Citation,
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
    headers: {
      "Content-Type": "application/json",
      Accept: "text/event-stream",
    },
    body: JSON.stringify(req),
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

    try {
      const evt = JSON.parse(payload) as ChatStreamEvent;
      if (evt.type === "token") handlers.onToken(evt.text);
      else if (evt.type === "citations") handlers.onCitations(evt.citations);
      else if (evt.type === "error") throw new Error(evt.detail);
    } catch {
      // Tolerate servers that stream raw text deltas instead of JSON.
      handlers.onToken(payload);
    }
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

  const res = await fetch(`${API_BASE}/ingest`, { method: "POST", body: form });

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
