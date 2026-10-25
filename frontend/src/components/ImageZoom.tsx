import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import type { ImageRef } from "../api";

interface ZoomItem {
  image: ImageRef;
  title?: string;
  pdfUrl?: string;
}

interface ZoomState {
  items: ZoomItem[];
  index: number;
}

const ZoomContext = createContext<(items: ZoomItem[], index?: number) => void>(() => {});

/** Kép nagyítása modalban: kattintásra / Esc-re bezárul, nyilakkal lapozható a galéria. */
export function ZoomProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<ZoomState | null>(null);
  const open = useCallback((items: ZoomItem[], index = 0) => setState({ items, index }), []);
  const close = () => setState(null);
  const step = (d: number) =>
    setState((s) => (s ? { ...s, index: (s.index + d + s.items.length) % s.items.length } : s));

  useEffect(() => {
    if (!state) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") close();
      if (e.key === "ArrowRight") step(1);
      if (e.key === "ArrowLeft") step(-1);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [state]);

  const cur = state ? state.items[state.index] : null;
  return (
    <ZoomContext.Provider value={open}>
      {children}
      {cur && (
        <div className="zoom" role="dialog" aria-modal="true" aria-label="Kép nagyítva" onClick={close}>
          <div className="zoom-box" onClick={(e) => e.stopPropagation()}>
            <div className="zoom-head">
              <div className="zoom-title">
                {cur.title && <b>{cur.title}</b>}
                <span>
                  {cur.image.page ? `${cur.image.page}. oldal` : ""}
                  {state!.items.length > 1 ? ` · ${state!.index + 1} / ${state!.items.length}` : ""}
                </span>
              </div>
              {cur.pdfUrl && (
                <a className="btn btn-ghost" href={cur.pdfUrl} target="_blank" rel="noreferrer">
                  PDF ezen az oldalon ↗
                </a>
              )}
              <button className="btn btn-ghost" onClick={close} aria-label="Bezárás (Esc)" title="Bezárás (Esc)">
                ✕
              </button>
            </div>
            <div className="zoom-img">
              {state!.items.length > 1 && (
                <button className="zoom-nav left" onClick={() => step(-1)} aria-label="Előző kép">‹</button>
              )}
              <img src={cur.image.url} alt={cur.image.caption ?? cur.image.description ?? "kép az útmutatóból"} />
              {state!.items.length > 1 && (
                <button className="zoom-nav right" onClick={() => step(1)} aria-label="Következő kép">›</button>
              )}
            </div>
            {(cur.image.caption || cur.image.description) && (
              <div className="zoom-caption">
                {cur.image.caption && <b>{cur.image.caption}</b>}
                {cur.image.description && <p>{cur.image.description}</p>}
              </div>
            )}
          </div>
        </div>
      )}
    </ZoomContext.Provider>
  );
}

export const useZoom = () => useContext(ZoomContext);

export function pdfPageUrl(documentId: number, page: number | null): string {
  return `/files/${documentId}.pdf${page ? `#page=${page}` : ""}`;
}
