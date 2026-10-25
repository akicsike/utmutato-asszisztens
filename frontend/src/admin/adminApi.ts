// Admin-hívások: minden kérés az X-Admin-Secret fejlécet viszi (a titok a sessionStorage-ban, csak a fülön él).

const KEY = "utmutato.adminSecret";

export function getSecret(): string {
  try {
    return sessionStorage.getItem(KEY) ?? "";
  } catch {
    return "";
  }
}

export function setSecret(v: string | null) {
  try {
    if (v) sessionStorage.setItem(KEY, v);
    else sessionStorage.removeItem(KEY);
  } catch {
    /* privát mód */
  }
}

export class AuthError extends Error {}

export async function adminFetch<T>(url: string, init: RequestInit = {}): Promise<T> {
  const headers: Record<string, string> = { "X-Admin-Secret": getSecret() };
  if (init.body && !(init.body instanceof FormData)) headers["Content-Type"] = "application/json";
  const res = await fetch(url, { ...init, headers: { ...headers, ...(init.headers as Record<string, string>) } });
  if (res.status === 401 || res.status === 403) throw new AuthError("Hibás admin jelszó");
  if (!res.ok) {
    let msg = `${res.status} ${res.statusText}`;
    try {
      const b = await res.json();
      if (b?.detail) msg = typeof b.detail === "string" ? b.detail : JSON.stringify(b.detail);
    } catch {
      /* nem JSON */
    }
    throw new Error(msg);
  }
  return res.json() as Promise<T>;
}

export interface DocRow {
  id: number;
  title: string;
  product: string | null;
  brand: string | null;
  filename: string;
  source: string;
  pages: number | null;
  status: "queued" | "parsing" | "images" | "indexing" | "indexed" | "error";
  stage_info: string | null;
  scanned: boolean | null;
  ocr_pages: number[] | null;
  parse_seconds: number | null;
  index_seconds: number | null;
  n_chunks: number;
  n_images: number;
  error: string | null;
  created_at: string;
  updated_at: string;
  file_size: number | null;
  parse_mode?: string | null;
}

export interface DocDetail extends DocRow {
  parse_info: Record<string, unknown> | null;
  chunk_counts: { strategy: string; kind: string; n: number }[];
  image_counts: { total: number; visible: number; described: number };
  jobs: { id: number; kind: string; status: string; error: string | null; created_at: string; finished_at: string | null }[];
  manual_fields: string[] | null;
}

export interface ChunkRow {
  id: number;
  seq: number;
  kind: string;
  text: string;
  embed_text: string;
  section: string | null;
  page_from: number | null;
  page_to: number | null;
  image_ids: number[] | null;
  token_count: number;
}

export interface ImageRow {
  id: number;
  page: number | null;
  width: number | null;
  height: number | null;
  caption: string | null;
  section: string | null;
  ocr_text: string | null;
  description: string | null;
  vlm_model: string | null;
  skipped_reason: string | null;
  manual_hidden: boolean | null;
}

export const BUSY = new Set(["queued", "parsing", "images", "indexing"]);

export const STATUS_LABEL: Record<string, string> = {
  queued: "sorban áll",
  parsing: "beolvasás (Docling/OCR)",
  images: "képek (VLM)",
  indexing: "indexelés",
  indexed: "kész",
  error: "hiba",
};
