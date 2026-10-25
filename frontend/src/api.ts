// Típusok + a backend hívásai (chat SSE-stream, beszélgetések, visszajelzés, admin).

export interface ImageRef {
  id: number;
  url: string;
  page: number | null;
  caption: string | null;
  description: string | null;
  width: number | null;
  height: number | null;
}

export interface Source {
  n: number;
  chunk_id: number;
  document_id: number;
  title: string;
  product: string | null;
  kind: "text" | "image";
  text: string;
  section: string | null;
  page_from: number | null;
  page_to: number | null;
  pdf_url: string;
  images: ImageRef[];
  score: number | null;
  dense_rank: number | null;
  bm25_rank: number | null;
}

export interface Usage {
  prompt_tokens: number;
  completion_tokens: number;
  cost_usd: number;
  ttft_ms?: number;
  total_ms?: number;
  rewrite_ms?: number;
  dense_ms?: number;
  bm25_ms?: number;
  rerank_ms?: number;
  llm_ms?: number;
  strategy?: string;
  chat_model?: string;
  by_purpose?: { purpose: string; model: string; prompt_tokens: number; completion_tokens: number; cost_usd: number; calls: number }[];
}

export interface Feedback {
  rating: "up" | "down";
  reasons: string[];
  comment: string | null;
}

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  sources: Source[];
  cited: number[];
  usage: Usage | null;
  error: string | null;
  searchQuery?: string | null;
  feedback?: Feedback | null;
  stage?: "rewrite" | "search" | "answer" | null; // folyamatban lévő válasznál
}

export interface Conversation {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
  n_messages: number;
}

export interface AppConfig {
  examples: string[];
  devices: string[];
  feedback_reasons: { code: string; label: string }[];
  strategies: string[];
  default_strategy: string;
  chat_model: string;
}

export type ChatEvent =
  | { type: "meta"; conversation_id: string; message_id: string; user_message_id: string }
  | { type: "plan"; query: string; intent: string; device: string | null }
  | { type: "sources"; sources: Source[] }
  | { type: "delta"; text: string }
  | { type: "done"; message_id: string; cited: number[]; usage: Usage; trace_id: string | null }
  | { type: "error"; message: string };

// A böngésző azonosítója: a beszélgetések ehhez kötődnek (nincs bejelentkezés).
export function clientId(): string {
  const KEY = "utmutato.clientId";
  try {
    let id = localStorage.getItem(KEY);
    if (!id) {
      id = crypto.randomUUID();
      localStorage.setItem(KEY, id);
    }
    return id;
  } catch {
    return (window as unknown as { __cid?: string }).__cid ??= crypto.randomUUID();
  }
}

async function request<T>(url: string, init: RequestInit = {}): Promise<T> {
  const res = await fetch(url, {
    ...init,
    headers: { "Content-Type": "application/json", "X-Client-Id": clientId(), ...(init.headers ?? {}) },
  });
  if (!res.ok) {
    let msg = `${res.status} ${res.statusText}`;
    try {
      const body = await res.json();
      if (body?.detail) msg = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch {
      /* nem JSON */
    }
    throw new Error(msg);
  }
  return res.json() as Promise<T>;
}

export const api = {
  config: () => request<AppConfig>("/api/config"),
  conversations: () => request<{ conversations: Conversation[] }>("/api/conversations"),
  conversation: (id: string) =>
    request<{ conversation: Conversation; messages: RawMessage[] }>(`/api/conversations/${id}`),
  renameConversation: (id: string, title: string) =>
    request(`/api/conversations/${id}`, { method: "PATCH", body: JSON.stringify({ title }) }),
  deleteConversation: (id: string) => request(`/api/conversations/${id}`, { method: "DELETE" }),
  feedback: (message_id: string, fb: Feedback) =>
    request("/api/feedback", { method: "POST", body: JSON.stringify({ message_id, ...fb }) }),
};

export interface RawMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  search_query: string | null;
  sources: Source[] | null;
  cited: number[] | null;
  usage: Usage | null;
  error: string | null;
  feedback_rating: "up" | "down" | null;
  feedback_reasons: string[] | null;
  feedback_comment: string | null;
}

export function fromRaw(m: RawMessage): ChatMessage {
  return {
    id: m.id,
    role: m.role,
    content: m.content,
    sources: m.sources ?? [],
    cited: m.cited ?? [],
    usage: m.usage,
    error: m.error,
    searchQuery: m.search_query,
    feedback: m.feedback_rating
      ? { rating: m.feedback_rating, reasons: m.feedback_reasons ?? [], comment: m.feedback_comment }
      : null,
  };
}

/** POST /api/chat – az SSE-eseményeket egyenként adja vissza a callbacknek. */
export async function streamChat(
  body: { message: string; conversation_id: string | null },
  onEvent: (ev: ChatEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const res = await fetch("/api/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Client-Id": clientId() },
    body: JSON.stringify(body),
    signal,
  });
  if (!res.ok || !res.body) throw new Error(`${res.status} ${res.statusText}`);
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buf = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    let idx;
    while ((idx = buf.indexOf("\n\n")) >= 0) {
      const frame = buf.slice(0, idx);
      buf = buf.slice(idx + 2);
      const data = frame
        .split("\n")
        .filter((l) => l.startsWith("data:"))
        .map((l) => l.slice(5).trimStart())
        .join("\n");
      if (data) onEvent(JSON.parse(data) as ChatEvent);
    }
  }
}

// ---------------------------------------------------------------- formázás

export const fmtMs = (ms?: number | null) =>
  ms == null ? "–" : ms < 1000 ? `${Math.round(ms)} ms` : `${(ms / 1000).toFixed(1).replace(".", ",")} s`;

export const fmtUsd = (v?: number | null) =>
  v == null ? "–" : v === 0 ? "$0" : v < 0.01 ? `$${v.toFixed(4)}` : `$${v.toFixed(2)}`;

export const fmtInt = (v?: number | null) => (v == null ? "–" : Math.round(v).toLocaleString("hu-HU"));

export function pageLabel(from: number | null, to: number | null): string {
  if (!from) return "";
  return to && to !== from ? `${from}–${to}. oldal` : `${from}. oldal`;
}
