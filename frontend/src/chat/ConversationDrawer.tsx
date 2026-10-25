import { useEffect, useState } from "react";
import type { Conversation } from "../api";

interface Props {
  open: boolean;
  conversations: Conversation[];
  currentId: string | null;
  onClose: () => void;
  onOpen: (id: string) => void;
  onNew: () => void;
  onRename: (id: string, title: string) => Promise<void>;
  onDelete: (id: string) => Promise<void>;
}

const fmtDate = (s: string) =>
  new Date(s).toLocaleString("hu-HU", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });

/** Bal oldalról becsúszó lista: korábbi beszélgetések megnyitása, átnevezése, törlése. */
export default function ConversationDrawer(p: Props) {
  const [editing, setEditing] = useState<string | null>(null);
  const [title, setTitle] = useState("");
  const [confirmDel, setConfirmDel] = useState<string | null>(null);

  useEffect(() => {
    if (!p.open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && p.onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [p.open, p.onClose]);

  if (!p.open) return null;
  return (
    <div className="drawer-backdrop" onClick={p.onClose}>
      <nav className="drawer" onClick={(e) => e.stopPropagation()} aria-label="Beszélgetések">
        <div className="drawer-head">
          <h2>Beszélgetések</h2>
          <button className="btn btn-ghost" onClick={p.onClose} aria-label="Bezárás">✕</button>
        </div>
        <button className="btn btn-primary drawer-new" onClick={p.onNew}>＋ Új beszélgetés</button>
        <div className="drawer-list">
          {p.conversations.length === 0 && <div className="empty">Még nincs mentett beszélgetés.</div>}
          {p.conversations.map((c) => (
            <div key={c.id} className={`conv${c.id === p.currentId ? " current" : ""}`}>
              {editing === c.id ? (
                <form
                  className="conv-edit"
                  onSubmit={async (e) => {
                    e.preventDefault();
                    if (title.trim()) await p.onRename(c.id, title.trim());
                    setEditing(null);
                  }}
                >
                  <input autoFocus value={title} maxLength={120} onChange={(e) => setTitle(e.target.value)} />
                  <button className="btn btn-sm btn-primary" type="submit">Mentés</button>
                  <button className="btn btn-sm btn-ghost" type="button" onClick={() => setEditing(null)}>Mégse</button>
                </form>
              ) : confirmDel === c.id ? (
                <div className="conv-edit">
                  <span>Törlöd?</span>
                  <button className="btn btn-sm btn-danger" onClick={async () => { await p.onDelete(c.id); setConfirmDel(null); }}>
                    Törlés
                  </button>
                  <button className="btn btn-sm btn-ghost" onClick={() => setConfirmDel(null)}>Mégse</button>
                </div>
              ) : (
                <>
                  <button className="conv-main" onClick={() => p.onOpen(c.id)}>
                    <span className="conv-title">{c.title}</span>
                    <span className="muted">{fmtDate(c.updated_at)} · {Math.ceil(c.n_messages / 2)} kérdés</span>
                  </button>
                  <button className="icon-btn" title="Átnevezés" onClick={() => { setEditing(c.id); setTitle(c.title); }}>✎</button>
                  <button className="icon-btn" title="Törlés" onClick={() => setConfirmDel(c.id)}>🗑</button>
                </>
              )}
            </div>
          ))}
        </div>
      </nav>
    </div>
  );
}
