import { useCallback, useEffect, useRef, useState } from "react";
import { fmtInt, pageLabel } from "../api";
import { pdfPageUrl, useZoom } from "../components/ImageZoom";
import {
  adminFetch,
  BUSY,
  STATUS_LABEL,
  type ChunkRow,
  type DocDetail,
  type DocRow,
  type ImageRow,
} from "./adminApi";
import { metricHelp } from "./metricHelp";

interface Props {
  onAuthError: (e: unknown) => void;
}

const fmtSize = (b: number | null) => (b == null ? "–" : b > 1 << 20 ? `${(b / (1 << 20)).toFixed(1)} MB` : `${Math.round(b / 1024)} KB`);

export default function DocumentsTab({ onAuthError }: Props) {
  const [docs, setDocs] = useState<DocRow[]>([]);
  const [filter, setFilter] = useState("");
  const [selected, setSelected] = useState<number | null>(null);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [drag, setDrag] = useState(false);
  const [uploading, setUploading] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  const load = useCallback(() => {
    adminFetch<{ documents: DocRow[] }>("/api/admin/documents")
      .then((r) => setDocs(r.documents))
      .catch(onAuthError);
  }, [onAuthError]);

  useEffect(load, [load]);
  const anyBusy = docs.some((d) => BUSY.has(d.status));
  useEffect(() => {
    if (!anyBusy) return;
    const t = setInterval(load, 3000);
    return () => clearInterval(t);
  }, [anyBusy, load]);

  async function upload(files: FileList | File[]) {
    const list = [...files].filter((f) => f.name.toLowerCase().endsWith(".pdf"));
    if (!list.length) return setMsg({ ok: false, text: "Csak PDF fájl tölthető fel." });
    const fd = new FormData();
    list.forEach((f) => fd.append("files", f));
    setUploading(true);
    try {
      const r = await adminFetch<{ results: { filename: string; status: string; error?: string }[] }>(
        "/api/admin/upload", { method: "POST", body: fd });
      const q = r.results.filter((x) => x.status === "queued").length;
      const dup = r.results.filter((x) => x.status === "duplicate").map((x) => x.filename);
      const rej = r.results.filter((x) => x.status === "rejected").map((x) => `${x.filename}: ${x.error}`);
      setMsg({
        ok: rej.length === 0,
        text: [`${q} fájl feldolgozásra vár.`, dup.length ? `Már fent van: ${dup.join(", ")}.` : "", rej.join("; ")]
          .filter(Boolean).join(" "),
      });
      load();
    } catch (e) {
      onAuthError(e);
      setMsg({ ok: false, text: (e as Error).message });
    } finally {
      setUploading(false);
    }
  }

  async function action(url: string, method = "POST", confirmText?: string) {
    if (confirmText && !window.confirm(confirmText)) return;
    try {
      await adminFetch(url, { method });
      load();
    } catch (e) {
      onAuthError(e);
      setMsg({ ok: false, text: (e as Error).message });
    }
  }

  const shown = docs.filter((d) =>
    `${d.title} ${d.product ?? ""} ${d.filename}`.toLowerCase().includes(filter.toLowerCase()));
  const totals = {
    docs: docs.length,
    indexed: docs.filter((d) => d.status === "indexed").length,
    pages: docs.reduce((a, d) => a + (d.pages ?? 0), 0),
    chunks: docs.reduce((a, d) => a + d.n_chunks, 0),
    images: docs.reduce((a, d) => a + d.n_images, 0),
    ocr: docs.filter((d) => (d.ocr_pages ?? []).length > 0).length,
  };

  return (
    <div className="admin-grid">
      <div className="kpis">
        <Kpi label="útmutató" value={`${totals.indexed} / ${totals.docs}`} />
        <Kpi label="oldal" value={fmtInt(totals.pages)} />
        <Kpi label="chunk (hibrid)" value={fmtInt(totals.chunks)} />
        <Kpi label="kép" value={fmtInt(totals.images)} />
        <Kpi label="OCR-es útmutató" value={String(totals.ocr)} />
      </div>

      <div
        className={`dropzone${drag ? " drag" : ""}`}
        onDragOver={(e) => { e.preventDefault(); setDrag(true); }}
        onDragLeave={() => setDrag(false)}
        onDrop={(e) => { e.preventDefault(); setDrag(false); upload(e.dataTransfer.files); }}
      >
        <div>
          <b>PDF feltöltése</b> – húzd ide a fájlokat, vagy{" "}
          <button className="link big" onClick={() => fileRef.current?.click()} disabled={uploading}>
            válaszd ki őket
          </button>
          <div className="muted">
            A szöveges PDF-ek Docling-gal, a képalapú (szkennelt) oldalak Tesseract OCR-rel (magyar + angol) olvasódnak be;
            a képekről VLM-leírás készül. Max. 200 MB / fájl.
          </div>
        </div>
        <input ref={fileRef} type="file" accept="application/pdf,.pdf" multiple hidden
               onChange={(e) => { if (e.target.files) upload(e.target.files); e.target.value = ""; }} />
        <div className="dropzone-actions">
          <button className="btn" onClick={() => action("/api/admin/import-seed")}>Kezdő mappa importálása</button>
          <button className="btn" onClick={() => action("/api/admin/reindex-all", "POST", "Minden útmutató újraindexelése (chunkolás + embedding)?")}>
            Mind újraindexelése
          </button>
        </div>
      </div>
      {uploading && <div className="notice pulse">Feltöltés…</div>}
      {msg && <div className={`notice ${msg.ok ? "ok" : "bad"}`}>{msg.text}</div>}

      <div className="panel">
        <div className="panel-head">
          <h2>Útmutatók</h2>
          {anyBusy && <span className="muted pulse">feldolgozás folyamatban – automatikus frissítés</span>}
          <input className="search" placeholder="Szűrés név szerint…" value={filter} onChange={(e) => setFilter(e.target.value)} />
        </div>
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th>Útmutató</th><th>Állapot</th><th className="r">Oldal</th><th>OCR</th>
                <th className="r">Chunk</th><th className="r">Kép</th><th className="r">Beolvasás</th><th className="r">Méret</th><th />
              </tr>
            </thead>
            <tbody>
              {shown.map((d) => (
                <tr key={d.id} className={selected === d.id ? "sel" : ""}>
                  <td>
                    <button className="link strong" onClick={() => setSelected(d.id)}>{d.title}</button>
                    <div className="muted">{d.product ?? "–"} · {d.filename}</div>
                  </td>
                  <td>
                    <span className={`status st-${d.status}`}>{STATUS_LABEL[d.status] ?? d.status}</span>
                    {d.stage_info && BUSY.has(d.status) && <div className="muted">{d.stage_info}</div>}
                    {d.error && <div className="err-small" title={d.error}>{d.error.slice(0, 80)}</div>}
                  </td>
                  <td className="r">{d.pages ?? "–"}</td>
                  <td>
                    {d.scanned ? <span className="tag ocr">teljes OCR</span>
                      : (d.ocr_pages ?? []).length ? <span className="tag ocr-part">{d.ocr_pages!.length} oldal</span> : "–"}
                  </td>
                  <td className="r">{d.n_chunks}</td>
                  <td className="r">{d.n_images}</td>
                  <td className="r">{d.parse_seconds ? `${Math.round(d.parse_seconds)} s` : "–"}</td>
                  <td className="r">{fmtSize(d.file_size)}</td>
                  <td className="actions">
                    <a className="btn btn-sm btn-ghost" href={pdfPageUrl(d.id, null)} target="_blank" rel="noreferrer" title="PDF megnyitása">PDF ↗</a>
                    <button className="btn btn-sm btn-ghost" disabled={BUSY.has(d.status)} title="Teljes újrafeldolgozás (Docling + OCR + képek + index)"
                            onClick={() => action(`/api/admin/documents/${d.id}/reprocess`)}>↻</button>
                    <button className="btn btn-sm btn-ghost danger" title="Törlés"
                            onClick={() => action(`/api/admin/documents/${d.id}`, "DELETE", `Törlöd: ${d.title}?`)}>🗑</button>
                  </td>
                </tr>
              ))}
              {shown.length === 0 && (
                <tr><td colSpan={9} className="empty">Nincs útmutató. Tölts fel PDF-et, vagy importáld a kezdő mappát.</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      {selected != null && (
        <DocDrawer id={selected} onClose={() => setSelected(null)} onChanged={load} onAuthError={onAuthError} />
      )}
    </div>
  );
}

export function Kpi({ label, value, hint, warn }: { label: string; value: string; hint?: string; warn?: boolean }) {
  return (
    <div className={`kpi${warn ? " warn" : ""}`} title={[metricHelp(label), hint].filter(Boolean).join("\n\n") || undefined}>
      <b>{value}</b>
      <span>{label}</span>
    </div>
  );
}

function DocDrawer({ id, onClose, onChanged, onAuthError }: { id: number; onClose: () => void; onChanged: () => void; onAuthError: (e: unknown) => void }) {
  const [doc, setDoc] = useState<DocDetail | null>(null);
  const [view, setView] = useState<"chunks" | "images" | "info">("chunks");
  const [strategy, setStrategy] = useState("hybrid");
  const [chunks, setChunks] = useState<ChunkRow[]>([]);
  const [images, setImages] = useState<ImageRow[]>([]);
  const [edit, setEdit] = useState<{ title: string; product: string; brand: string } | null>(null);
  const zoom = useZoom();

  const load = useCallback(() => {
    adminFetch<DocDetail>(`/api/admin/documents/${id}`).then(setDoc).catch(onAuthError);
    adminFetch<{ images: ImageRow[] }>(`/api/admin/documents/${id}/images`).then((r) => setImages(r.images)).catch(onAuthError);
  }, [id, onAuthError]);
  useEffect(load, [load]);
  useEffect(() => {
    adminFetch<{ chunks: ChunkRow[] }>(`/api/admin/documents/${id}/chunks?strategy=${strategy}`)
      .then((r) => setChunks(r.chunks)).catch(onAuthError);
  }, [id, strategy, onAuthError]);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  async function saveMeta() {
    if (!edit) return;
    await adminFetch(`/api/admin/documents/${id}`, { method: "PATCH", body: JSON.stringify(edit) }).catch(onAuthError);
    setEdit(null);
    load();
    onChanged();
  }

  async function toggleImage(im: ImageRow) {
    const visible = im.manual_hidden === false || (im.manual_hidden == null && !im.skipped_reason);
    await adminFetch(`/api/admin/images/${im.id}`, { method: "PATCH", body: JSON.stringify({ hidden: visible }) }).catch(onAuthError);
    load();
    onChanged();
  }

  return (
    <div className="drawer-backdrop" onClick={onClose}>
      <aside className="drawer right wide" onClick={(e) => e.stopPropagation()}>
        <div className="drawer-head">
          <div>
            <h2>Útmutató #{id}</h2>
            <b>{doc?.title}</b>
          </div>
          <button className="btn btn-ghost" onClick={onClose} aria-label="Bezárás">✕</button>
        </div>
        {doc && (
          <div className="drawer-scroll">
            {edit ? (
              <div className="meta-edit">
                <label>Cím<input value={edit.title} onChange={(e) => setEdit({ ...edit, title: e.target.value })} /></label>
                <label>Terméktípus<input value={edit.product} onChange={(e) => setEdit({ ...edit, product: e.target.value })} /></label>
                <label>Márka<input value={edit.brand} onChange={(e) => setEdit({ ...edit, brand: e.target.value })} /></label>
                <div className="muted">Mentés után az útmutató újraindexelődik (a cím minden chunk kontextus-előtagjában szerepel).</div>
                <div className="fb-actions">
                  <button className="btn btn-ghost" onClick={() => setEdit(null)}>Mégse</button>
                  <button className="btn btn-primary" onClick={saveMeta}>Mentés</button>
                </div>
              </div>
            ) : (
              <div className="meta-row">
                <span>{doc.product ?? "–"} · {doc.brand ?? "–"} · {doc.pages} oldal · mód: <b>{doc.parse_mode ?? "–"}</b>
                  {(doc.ocr_pages ?? []).length > 0 && <> · OCR-oldalak: {doc.ocr_pages!.join(", ")}</>}
                </span>
                <button className="btn btn-sm" onClick={() => setEdit({ title: doc.title, product: doc.product ?? "", brand: doc.brand ?? "" })}>
                  Adatok szerkesztése
                </button>
                <button className="btn btn-sm" onClick={() => adminFetch(`/api/admin/documents/${id}/reindex`, { method: "POST" }).then(onChanged)}>
                  Újraindexelés
                </button>
              </div>
            )}
            <div className="seg">
              {(["chunks", "images", "info"] as const).map((v) => (
                <button key={v} className={view === v ? "on" : ""} onClick={() => setView(v)}>
                  {v === "chunks" ? `Chunkok (${chunks.length})` : v === "images" ? `Képek (${images.length})` : "Feldolgozás"}
                </button>
              ))}
              {view === "chunks" && (
                <select value={strategy} onChange={(e) => setStrategy(e.target.value)} title="Chunk-stratégia">
                  <option value="hybrid">hibrid (szerkezet szerint)</option>
                  <option value="fixed">fix tokenablak</option>
                </select>
              )}
            </div>

            {view === "chunks" && chunks.map((c) => (
              <div key={c.id} className="chunk">
                <div className="chunk-head">
                  <span className="num">{c.seq}</span>
                  {c.kind === "image" && <span className="tag">kép</span>}
                  <span>{pageLabel(c.page_from, c.page_to)}</span>
                  <span className="muted">{c.token_count} token{c.image_ids?.length ? ` · ${c.image_ids.length} kép` : ""}</span>
                  {c.page_from && <a className="btn btn-sm btn-ghost" href={pdfPageUrl(id, c.page_from)} target="_blank" rel="noreferrer">↗</a>}
                </div>
                {c.section && <div className="src-section">{c.section}</div>}
                <div className="chunk-text">{c.text}</div>
              </div>
            ))}

            {view === "images" && (
              <div className="img-grid">
                {images.map((im, i) => {
                  const visible = im.manual_hidden === false || (im.manual_hidden == null && !im.skipped_reason);
                  return (
                    <div key={im.id} className={`img-card${visible ? "" : " hidden-img"}`}>
                      <button className="thumb big" onClick={() => zoom(images.map((x) => ({
                        image: { id: x.id, url: `/images/${x.id}`, page: x.page, caption: x.caption, description: x.description, width: x.width, height: x.height },
                        title: doc.title, pdfUrl: pdfPageUrl(id, x.page) })), i)}>
                        <img src={`/images/${im.id}`} alt={im.caption ?? "kép"} loading="lazy" />
                      </button>
                      <div className="muted">
                        {im.page}. oldal · {im.width}×{im.height}
                        {!visible && <> · <b>rejtett</b>{im.skipped_reason && !im.manual_hidden ? ` (${im.skipped_reason})` : ""}</>}
                      </div>
                      {im.caption && <div className="strong small">{im.caption}</div>}
                      {im.description && <div className="img-desc">{im.description}</div>}
                      <button className="btn btn-sm" onClick={() => toggleImage(im)}>{visible ? "Elrejtés" : "Megjelenítés"}</button>
                    </div>
                  );
                })}
              </div>
            )}

            {view === "info" && (
              <div className="info">
                <table className="table compact">
                  <tbody>
                    <tr><th>Fájl</th><td>{doc.filename}</td></tr>
                    <tr><th>Forrás</th><td>{doc.source}</td></tr>
                    <tr><th>Beolvasás</th><td>{doc.parse_seconds?.toFixed(1)} s</td></tr>
                    <tr><th>Indexelés</th><td>{doc.index_seconds?.toFixed(1)} s</td></tr>
                    <tr><th>Chunkok</th><td>{doc.chunk_counts.map((c) => `${c.strategy}/${c.kind}: ${c.n}`).join(" · ")}</td></tr>
                    <tr><th>Képek</th><td>{doc.image_counts.total} kivágott · {doc.image_counts.visible} látható · {doc.image_counts.described} VLM-leírással</td></tr>
                    {doc.manual_fields?.length ? <tr><th>Kézzel javítva</th><td>{doc.manual_fields.join(", ")}</td></tr> : null}
                  </tbody>
                </table>
                <h3>Feladatok</h3>
                <table className="table compact">
                  <tbody>
                    {doc.jobs.map((j) => (
                      <tr key={j.id}><td>#{j.id}</td><td>{j.kind}</td><td>{j.status}</td><td>{new Date(j.created_at).toLocaleString("hu-HU")}</td><td className="err-small">{j.error}</td></tr>
                    ))}
                  </tbody>
                </table>
                {doc.parse_info && <pre className="json">{JSON.stringify(doc.parse_info, null, 2)}</pre>}
              </div>
            )}
          </div>
        )}
      </aside>
    </div>
  );
}
