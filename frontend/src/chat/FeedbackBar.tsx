import { useState } from "react";
import { api, type ChatMessage, type Feedback } from "../api";

interface Props {
  message: ChatMessage;
  reasons: { code: string; label: string }[];
  onSaved: (fb: Feedback) => void;
}

/** 👍 azonnal ment; 👎 kinyitja az okokat (chipek) és a "Mit vártál volna?" mezőt. */
export default function FeedbackBar({ message, reasons, onSaved }: Props) {
  const saved = message.feedback ?? null;
  const [open, setOpen] = useState(false);
  const [picked, setPicked] = useState<string[]>(saved?.reasons ?? []);
  const [comment, setComment] = useState(saved?.comment ?? "");
  const [status, setStatus] = useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);

  async function save(fb: Feedback) {
    setBusy(true);
    setStatus(null);
    try {
      await api.feedback(message.id, fb);
      onSaved(fb);
      setOpen(false);
      setStatus({ ok: true, text: "Köszönjük a visszajelzést!" });
    } catch (e) {
      setStatus({ ok: false, text: (e as Error).message });
    } finally {
      setBusy(false);
    }
  }

  const toggle = (code: string) =>
    setPicked((p) => (p.includes(code) ? p.filter((x) => x !== code) : [...p, code]));

  return (
    <div className="feedback">
      <span className="muted">Hasznos volt?</span>
      <button
        className={`fb-btn${saved?.rating === "up" ? " on" : ""}`}
        disabled={busy}
        onClick={() => save({ rating: "up", reasons: [], comment: null })}
        aria-pressed={saved?.rating === "up"}
        title="Jó válasz"
      >
        👍
      </button>
      <button
        className={`fb-btn${saved?.rating === "down" ? " on down" : ""}`}
        disabled={busy}
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        aria-pressed={saved?.rating === "down"}
        title="Nem jó válasz – mondd el, miért"
      >
        👎
      </button>
      {status && <span className={status.ok ? "fb-ok" : "fb-err"}>{status.text}</span>}
      {open && (
        <div className="fb-form">
          <div className="fb-title">Mi volt a gond a válasszal?</div>
          <div className="chips">
            {reasons.map((r) => (
              <button key={r.code} className={`chip${picked.includes(r.code) ? " on" : ""}`}
                      onClick={() => toggle(r.code)} aria-pressed={picked.includes(r.code)}>
                {r.label}
              </button>
            ))}
          </div>
          <textarea
            rows={2}
            maxLength={2000}
            placeholder="Mit vártál volna? (pl. melyik lépés hiányzott, melyik útmutatóban kellett volna keresni)"
            value={comment}
            onChange={(e) => setComment(e.target.value)}
          />
          <div className="fb-actions">
            <button className="btn btn-ghost" onClick={() => setOpen(false)}>Mégse</button>
            <button
              className="btn btn-primary"
              disabled={busy || (picked.length === 0 && !comment.trim())}
              onClick={() => save({ rating: "down", reasons: picked, comment: comment.trim() || null })}
            >
              Küldés
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
