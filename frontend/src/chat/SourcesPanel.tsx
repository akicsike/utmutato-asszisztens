import { useEffect, useMemo, useRef, useState } from "react";
import { pageLabel, type ChatMessage, type Source } from "../api";
import { pdfPageUrl, useZoom } from "../components/ImageZoom";

interface Props {
  message: ChatMessage | null;
  flash: { n: number; key: number } | null;
}

interface DocGroup {
  document_id: number;
  title: string;
  product: string | null;
  items: Source[];
}

/** Bal panel: a kiválasztott válasz forrásai útmutatónként csoportosítva; a hivatkozottak kiemelve. */
export default function SourcesPanel({ message, flash }: Props) {
  const sources = message?.sources ?? [];
  const cited = new Set(message?.cited ?? []);
  const groups = useMemo(() => {
    const map = new Map<number, DocGroup>();
    for (const s of sources) {
      if (!map.has(s.document_id))
        map.set(s.document_id, { document_id: s.document_id, title: s.title, product: s.product, items: [] });
      map.get(s.document_id)!.items.push(s);
    }
    // a hivatkozott forrást tartalmazó útmutatók előre
    return [...map.values()].sort(
      (a, b) => Number(b.items.some((s) => cited.has(s.n))) - Number(a.items.some((s) => cited.has(s.n))),
    );
  }, [sources, message?.cited]);

  return (
    <div className="panel sources">
      <div className="panel-head">
        <h2>Források</h2>
        {sources.length > 0 && (
          <span className="muted">
            {sources.length} részlet · {groups.length} útmutató
            {cited.size > 0 && <> · <b className="accent">{cited.size} hivatkozott</b></>}
          </span>
        )}
      </div>
      {message?.searchQuery && sources.length > 0 && (
        <div className="search-query" title="Ezzel a (beszélgetésből kiegészített) kérdéssel keresett a rendszer">
          Keresés: <i>{message.searchQuery}</i>
        </div>
      )}
      <div className="panel-body">
        {!message || message.stage === "rewrite" || message.stage === "search" ? (
          <div className="empty">
            {message?.stage ? (
              <span className="pulse">Keresés az útmutatókban…</span>
            ) : (
              <>
                Itt jelennek meg a válaszhoz felhasznált útmutató-részletek: melyik útmutató, melyik oldal, a
                teljes szöveg és a képek. A PDF az adott oldalon nyílik meg új lapon.
              </>
            )}
          </div>
        ) : sources.length === 0 ? (
          <div className="empty">Ehhez a válaszhoz nem tartozik forrás.</div>
        ) : (
          groups.map((g) => (
            <section key={g.document_id} className="doc-group">
              <header className="doc-head">
                <div className="doc-icon" aria-hidden>
                  PDF
                </div>
                <div className="doc-title">
                  <b>{g.title}</b>
                  {g.product && <span className="muted">{g.product}</span>}
                </div>
                <a className="btn btn-sm" href={pdfPageUrl(g.document_id, null)} target="_blank" rel="noreferrer"
                   title="A teljes útmutató megnyitása új lapon">
                  Megnyitás ↗
                </a>
              </header>
              {g.items.map((s) => (
                <SourceItem key={s.n} source={s} cited={cited.has(s.n)} flash={flash?.n === s.n ? flash.key : null} />
              ))}
            </section>
          ))
        )}
      </div>
    </div>
  );
}

function SourceItem({ source: s, cited, flash }: { source: Source; cited: boolean; flash: number | null }) {
  const [open, setOpen] = useState(false);
  const [lit, setLit] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const zoom = useZoom();
  const long = s.text.length > 260;

  useEffect(() => {
    if (flash == null) return;
    setOpen(true);
    setLit(true);
    ref.current?.scrollIntoView({ behavior: "smooth", block: "center" });
    const t = setTimeout(() => setLit(false), 1600);
    return () => clearTimeout(t);
  }, [flash]);

  const zoomItems = s.images.map((im) => ({ image: im, title: s.title, pdfUrl: pdfPageUrl(s.document_id, im.page) }));

  return (
    <div ref={ref} className={`src${cited ? " cited" : ""}${lit ? " lit" : ""}`} id={`src-${s.n}`}>
      <div className="src-head">
        <span className="num" title={cited ? "A válasz hivatkozik rá" : "Felhasznált, de nem hivatkozott részlet"}>
          {s.n}
        </span>
        <div className="src-meta">
          <span className="src-loc">
            {s.kind === "image" && <span className="tag">kép</span>}
            {pageLabel(s.page_from, s.page_to) || "oldal ismeretlen"}
            {s.score != null && (
              <span className="score" title="Rerank-relevancia (0–1)">
                {" "}· {s.score.toFixed(2).replace(".", ",")}
              </span>
            )}
          </span>
          {s.section && <span className="src-section">{s.section}</span>}
        </div>
        {s.page_from && (
          <a className="btn btn-sm btn-ghost" href={s.pdf_url} target="_blank" rel="noreferrer"
             title={`PDF megnyitása a(z) ${s.page_from}. oldalon, új lapon`}>
            {s.page_from}. o. ↗
          </a>
        )}
      </div>
      <div className={`src-text${open || !long ? " full" : ""}`}>{s.text}</div>
      {long && (
        <button className="link" onClick={() => setOpen((o) => !o)}>
          {open ? "Kevesebb ▴" : "Teljes szöveg ▾"}
        </button>
      )}
      {s.images.length > 0 && (
        <div className="thumbs">
          {s.images.map((im, i) => (
            <button key={im.id} className="thumb" onClick={() => zoom(zoomItems, i)}
                    title={im.caption ?? im.description ?? "Nagyítás"}>
              <img src={im.url} alt={im.caption ?? "kép"} loading="lazy" />
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
