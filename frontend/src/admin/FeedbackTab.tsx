import { useCallback, useEffect, useState } from "react";
import { adminFetch } from "./adminApi";
import { CaseCheck, CHECK_HELP, EXPECT_LABEL, EvalCaseForm, type CheckResult, type EvalCaseRef } from "./evalCases";
import { Kpi } from "./DocumentsTab";

const REASON_LABEL: Record<string, string> = {
  teves: "Téves",
  nem_talalta: "Nem találta",
  hianyos: "Hiányos",
  rossz_forras: "Rossz forrás",
  rossz_kep: "Rossz kép",
  nehezen_ertheto: "Nehezen érthető",
};

type Status = "uj" | "vizsgalva" | "javitva" | "nem_hiba";
const STATUS_LABEL: Record<Status, string> = { uj: "Új", vizsgalva: "Vizsgálva", javitva: "Javítva", nem_hiba: "Nem hiba" };
const STATUSES = Object.keys(STATUS_LABEL) as Status[];

interface Source {
  n: number;
  title: string;
  document_id: number;
  kind: string;
  section: string | null;
  page_from: number | null;
  page_to: number | null;
  score: number | null;
  cited: boolean;
  pdf_url: string | null;
}

interface Item {
  rating: "up" | "down";
  reasons: string[];
  comment: string | null;
  updated_at: string;
  message_id: string;
  answer: string;
  question: string | null;
  documents: string[];
  status: Status;
  admin_note: string | null;
  status_at: string | null;
  search_query: string | null;
  sources: Source[];
  trace_url: string | null;
  eval_cases: EvalCaseRef[];
}

interface Analysis {
  id: number;
  model: string;
  n_feedback: number;
  created_at: string;
  result: {
    summary?: string;
    themes?: { title: string; description: string; count: number; examples: string[]; suggestion: string }[];
    documents_to_improve?: { title: string; issue: string }[];
    quick_wins?: string[];
  };
}

interface Resp {
  items: Item[];
  stats: {
    answers: number;
    rated: number;
    up: number;
    down: number;
    satisfaction: number | null;
    rated_share: number | null;
    reasons: [string, number][];
    down_by_document: [string, number][];
    down_by_status: Record<Status, number>;
  };
  rerank_min_score: number;
  latest_analysis: Analysis | null;
}

interface EvalCase {
  id: number;
  message_id: string | null;
  level: "rag" | "prompt";
  question: string;
  doc_file: string | null;
  doc_title: string | null;
  pages: number[] | null;
  expect: string | null;
  facts: string[] | null;
  created_at: string;
  last_check: CheckResult | null;
  last_check_at: string | null;
}

interface CasesResp {
  items: EvalCase[];
  yaml: { rag: string; prompt: string };
}

const pct = (v: number | null) => (v == null ? "–" : `${Math.round(v * 100)}%`);
const num2 = (v: number) => v.toFixed(2).replace(".", ",");
const pages = (s: Source) => (s.page_from == null ? "" : s.page_to && s.page_to !== s.page_from ? `${s.page_from}–${s.page_to}. o.` : `${s.page_from}. o.`);

/** Rövid, adatból levezetett tipp: melyik rétegben lehet a hiba (beolvasás / keresés / válasz). */
function diagnose(it: Item, thr: number): string | null {
  if (it.rating === "up") return null;
  const r = new Set(it.reasons);
  if (it.sources.length === 0) {
    return `Nem volt forrás a küszöb (${num2(thr)}) felett, ezért „nem találtam” lett a válasz. Ha a PDF-ben benne van: ` +
      "① Dokumentumok → az útmutató chunkjai – bekerült-e a szöveg (ha nem: beolvasási hiba → Újrafeldolgozás); " +
      "② ha bekerült: a Phoenix-trace rerank-lépésében hol van, és mennyi a pontja (keresési hiba).";
  }
  const top = Math.max(...it.sources.map((s) => s.score ?? 0));
  const shaky = top < thr + 0.1 ? ` A legjobb forrás rerank-pontja (${num2(top)}) a küszöb közelében van – bizonytalan keresés.` : "";
  if (r.has("nem_talalta") || r.has("rossz_forras")) {
    return "Valószínűleg keresési hiba: ha a helyes részlet nincs a lenti források között, nézd meg a Phoenix-trace-ben, hol van a " +
      "rangsorban; ha a Dokumentumok fülön sincs meg a szöveg, beolvasási hiba." + shaky;
  }
  if (r.has("teves") || r.has("hianyos")) {
    return "Ha a helyes részlet a lenti források között van, a válasz (a prompt) a hibás → system.md; ha nincs, a keresés." + shaky;
  }
  return shaky ? shaky.trim() : null;
}

export default function FeedbackTab({ onAuthError }: { onAuthError: (e: unknown) => void }) {
  const [data, setData] = useState<Resp | null>(null);
  const [cases, setCases] = useState<CasesResp | null>(null);
  const [rating, setRating] = useState<"" | "up" | "down">("");
  const [status, setStatus] = useState<"" | Status>("");
  const [analyzing, setAnalyzing] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const load = useCallback(() => {
    const q = new URLSearchParams();
    if (rating) q.set("rating", rating);
    if (status) q.set("status", status);
    adminFetch<Resp>(`/api/admin/feedback?${q}`).then(setData).catch(onAuthError);
  }, [rating, status, onAuthError]);
  const loadCases = useCallback(() => {
    adminFetch<CasesResp>("/api/admin/eval-cases").then(setCases).catch(onAuthError);
  }, [onAuthError]);
  useEffect(load, [load]);
  useEffect(loadCases, [loadCases]);

  async function analyze() {
    setAnalyzing(true);
    setErr(null);
    try {
      await adminFetch("/api/admin/feedback/analyze", { method: "POST" });
      load();
    } catch (e) {
      onAuthError(e);
      setErr((e as Error).message);
    } finally {
      setAnalyzing(false);
    }
  }

  if (!data) return <div className="page-loading">Betöltés…</div>;
  const s = data.stats;
  const maxReason = Math.max(1, ...s.reasons.map((r) => r[1]));
  const maxDoc = Math.max(1, ...s.down_by_document.map((r) => r[1]));
  const a = data.latest_analysis;
  const open = (s.down_by_status?.uj ?? 0) + (s.down_by_status?.vizsgalva ?? 0);

  return (
    <div className="admin-grid">
      <div className="kpis">
        <Kpi label="válasz összesen" value={String(s.answers)} />
        <Kpi label="értékelt" value={`${s.rated} (${pct(s.rated_share)})`} />
        <Kpi label="👍 jó" value={String(s.up)} />
        <Kpi label="👎 nem jó" value={String(s.down)} warn={s.down > 0} />
        <Kpi label="👎 nyitott (új + vizsgálva)" value={String(open)} warn={open > 0}
             hint="A negatív visszajelzések közül hány vár még javításra vagy döntésre." />
        <Kpi label="elégedettség" value={pct(s.satisfaction)} />
      </div>

      <div className="two-col">
        <div className="panel">
          <div className="panel-head"><h2>Negatív értékelés okai</h2></div>
          <div className="panel-body">
            {s.reasons.length === 0 && <div className="empty">Még nincs megjelölt ok.</div>}
            {s.reasons.map(([code, n]) => (
              <div key={code} className="bar-row">
                <span className="bar-label">{REASON_LABEL[code] ?? code}</span>
                <span className="bar"><span style={{ width: `${(n / maxReason) * 100}%` }} /></span>
                <span className="bar-val">{n}</span>
              </div>
            ))}
          </div>
        </div>
        <div className="panel">
          <div className="panel-head"><h2>👎 hivatkozott útmutatónként</h2></div>
          <div className="panel-body">
            {s.down_by_document.length === 0 && <div className="empty">Nincs negatív értékelés.</div>}
            {s.down_by_document.map(([title, n]) => (
              <div key={title} className="bar-row">
                <span className="bar-label" title={title}>{title}</span>
                <span className="bar warn"><span style={{ width: `${(n / maxDoc) * 100}%` }} /></span>
                <span className="bar-val">{n}</span>
              </div>
            ))}
          </div>
        </div>
      </div>

      <div className="panel">
        <div className="panel-head">
          <h2>LLM-es témaelemzés</h2>
          {a && <span className="muted">{new Date(a.created_at).toLocaleString("hu-HU")} · {a.n_feedback} negatív visszajelzés · {a.model}</span>}
          <button className="btn btn-primary push-right" onClick={analyze} disabled={analyzing || s.down === 0}>
            {analyzing ? "Elemzés…" : "Új elemzés"}
          </button>
        </div>
        <div className="panel-body">
          {err && <div className="notice bad">{err}</div>}
          {!a ? (
            <div className="empty">
              A negatív visszajelzésekből (okok + „mit vártál volna” szöveg + hivatkozott útmutatók) az LLM visszatérő
              témákat és javítási javaslatokat készít.
            </div>
          ) : (
            <div className="analysis">
              {a.result.summary && <p className="lead">{a.result.summary}</p>}
              <div className="themes">
                {(a.result.themes ?? []).map((t) => (
                  <div key={t.title} className="theme">
                    <div className="theme-head"><b>{t.title}</b><span className="tag">{t.count} db</span></div>
                    <p>{t.description}</p>
                    {t.examples?.length > 0 && <ul className="muted">{t.examples.map((e) => <li key={e}>{e}</li>)}</ul>}
                    <p className="suggestion">➜ {t.suggestion}</p>
                  </div>
                ))}
              </div>
              {(a.result.documents_to_improve ?? []).length > 0 && (
                <>
                  <h3>Javítandó útmutatók</h3>
                  <ul>{a.result.documents_to_improve!.map((d) => <li key={d.title}><b>{d.title}</b>: {d.issue}</li>)}</ul>
                </>
              )}
              {(a.result.quick_wins ?? []).length > 0 && (
                <>
                  <h3>Gyors javítások</h3>
                  <ul>{a.result.quick_wins!.map((q) => <li key={q}>{q}</li>)}</ul>
                </>
              )}
            </div>
          )}
        </div>
      </div>

      <div className="panel">
        <div className="panel-head">
          <h2>Visszajelzések</h2>
          <div className="seg small push-right" title="Szűrés állapot szerint">
            <button className={status === "" ? "on" : ""} onClick={() => setStatus("")}>Minden állapot</button>
            {STATUSES.map((st) => (
              <button key={st} className={status === st ? "on" : ""} onClick={() => setStatus(st)}>{STATUS_LABEL[st]}</button>
            ))}
          </div>
          <div className="seg small">
            {(["", "down", "up"] as const).map((r) => (
              <button key={r} className={rating === r ? "on" : ""} onClick={() => setRating(r)}>
                {r === "" ? "Mind" : r === "down" ? "👎" : "👍"}
              </button>
            ))}
          </div>
        </div>
        <div className="panel-body">
          {data.items.length === 0 && <div className="empty">Nincs visszajelzés.</div>}
          {data.items.map((it) => (
            <FeedbackItem key={it.message_id} it={it} thr={data.rerank_min_score} onAuthError={onAuthError}
                          onChanged={() => { load(); loadCases(); }} />
          ))}
        </div>
      </div>

      <EvalCasesPanel cases={cases} onAuthError={onAuthError} onChanged={() => { load(); loadCases(); }} />
    </div>
  );
}

function FeedbackItem({ it, thr, onAuthError, onChanged }: {
  it: Item; thr: number; onAuthError: (e: unknown) => void; onChanged: () => void;
}) {
  const [note, setNote] = useState(it.admin_note ?? "");
  const [formOpen, setFormOpen] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  useEffect(() => setNote(it.admin_note ?? ""), [it.admin_note]);

  async function patch(body: { status?: Status; admin_note?: string }) {
    try {
      await adminFetch(`/api/admin/feedback/${it.message_id}`, { method: "PATCH", body: JSON.stringify(body) });
      onChanged();
    } catch (e) {
      onAuthError(e);
      setMsg((e as Error).message);
    }
  }

  const hint = diagnose(it, thr);
  return (
    <div className={`fb-item ${it.rating}`}>
      <div className="fb-item-head">
        <span>{it.rating === "up" ? "👍" : "👎"}</span>
        <b>{it.question ?? "(kérdés nem található)"}</b>
        <span className={`fb-status ${it.status}`}>{STATUS_LABEL[it.status]}</span>
        <span className="muted push-right">{new Date(it.updated_at).toLocaleString("hu-HU")}</span>
      </div>
      {it.reasons.length > 0 && (
        <div className="chips small">{it.reasons.map((r) => <span key={r} className="chip on static">{REASON_LABEL[r] ?? r}</span>)}</div>
      )}
      {it.comment && <div className="fb-comment">„{it.comment}”</div>}

      <details>
        <summary className="muted">Válasz{it.documents.length ? ` · ${it.documents.join(", ")}` : ""}</summary>
        <div className="fb-answer">{it.answer}</div>
      </details>

      <div className="fb-diag">
        {it.search_query && it.search_query !== it.question && (
          <div className="muted" title="A kérdés-átíró LLM által készített önálló keresőkérdés – ezzel keresett a rendszer.">
            Keresőkérdés (átírás után): <i>{it.search_query}</i>
          </div>
        )}
        {it.sources.length > 0 ? (
          <table className="fb-src">
            <thead><tr><th>#</th><th>Forrás</th><th>Oldal</th><th title="Rerank-relevancia (0–1); a küszöb alatti forrás nem kerül a válaszba">Rerank</th></tr></thead>
            <tbody>
              {it.sources.map((s) => (
                <tr key={s.n} className={s.cited ? "cited" : ""}>
                  <td>{s.n}</td>
                  <td>
                    {s.title}{s.kind === "image" && <span className="tag">kép</span>}
                    {s.cited && <span className="tag cite" title="A válasz hivatkozik rá">hivatkozott</span>}
                    {s.section && <div className="muted">{s.section}</div>}
                  </td>
                  <td>{s.pdf_url ? <a href={s.pdf_url} target="_blank" rel="noreferrer">{pages(s)} ↗</a> : pages(s)}</td>
                  <td className={(s.score ?? 0) < thr + 0.1 ? "low" : ""}>{s.score == null ? "–" : num2(s.score)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <div className="muted">Nem volt forrás a küszöb felett.</div>
        )}
        {hint && <div className="fb-hint">💡 {hint}</div>}
      </div>

      <div className="fb-tools">
        <div className="seg small" title="A visszajelzés kezelésének állapota">
          {STATUSES.map((st) => (
            <button key={st} className={it.status === st ? "on" : ""} onClick={() => it.status !== st && patch({ status: st })}>
              {STATUS_LABEL[st]}
            </button>
          ))}
        </div>
        {it.trace_url && (
          <a className="btn btn-sm" href={it.trace_url} target="_blank" rel="noreferrer"
             title="A válasz nyoma a Phoenixben: átírás → keresés → rerank-pontok → LLM-hívás">🔎 Phoenix-trace ↗</a>
        )}
        <button className="btn btn-sm" onClick={() => setFormOpen((v) => !v)}>
          {formOpen ? "Mégse" : "➕ Felvétel a mérésbe"}
        </button>
      </div>
      {it.eval_cases.map((c) => (
        <CaseCheck key={c.id} id={c.id} level={c.level} lastCheck={c.last_check} lastCheckAt={c.last_check_at}
                   onAuthError={onAuthError} onDone={onChanged} />
      ))}
      <input className="fb-note" placeholder="Admin-megjegyzés (pl. mi volt a hiba, mit javítottál) – Enter vagy kattintás máshová ment"
             value={note} onChange={(e) => setNote(e.target.value)}
             onKeyDown={(e) => e.key === "Enter" && (e.target as HTMLInputElement).blur()}
             onBlur={() => note !== (it.admin_note ?? "") && patch({ admin_note: note })} />
      {msg && <div className="notice bad">{msg}</div>}
      {formOpen && (
        <EvalCaseForm messageId={it.message_id} question={it.question} docId={(it.sources.find((x) => x.cited) ?? it.sources[0])?.document_id}
                      facts={it.comment} onAuthError={onAuthError}
                      onSaved={() => { setFormOpen(false); onChanged(); }} />
      )}
    </div>
  );
}

function EvalCasesPanel({ cases, onAuthError, onChanged }: {
  cases: CasesResp | null; onAuthError: (e: unknown) => void; onChanged: () => void;
}) {
  const [copied, setCopied] = useState<string | null>(null);
  const [runningId, setRunningId] = useState<number | null>(null);
  if (!cases) return null;

  async function checkAll() {
    for (const c of [...cases!.items].reverse()) {
      setRunningId(c.id);
      try {
        await adminFetch(`/api/admin/eval-cases/${c.id}/check`, { method: "POST" });
      } catch (e) {
        onAuthError(e);
        break;
      }
      onChanged();
    }
    setRunningId(null);
  }

  async function remove(id: number) {
    if (!confirm(`Törlöd az fb${id} mérési esetet? (A visszajelzés megmarad.)`)) return;
    try {
      await adminFetch(`/api/admin/eval-cases/${id}`, { method: "DELETE" });
      onChanged();
    } catch (e) {
      onAuthError(e);
    }
  }
  async function copy(kind: "rag" | "prompt") {
    try {
      await navigator.clipboard.writeText(cases!.yaml[kind]);
      setCopied(kind);
    } catch {
      setCopied(null);
    }
    setTimeout(() => setCopied(null), 1500);
  }

  return (
    <div className="panel">
      <div className="panel-head">
        <h2>Mérési esetek visszajelzésből</h2>
        <span className="muted">{cases.items.length} eset · a következő mérési futás ezeket is méri (azonosító: fb…)</span>
      </div>
      <div className="panel-body">
        {cases.items.length === 0 ? (
          <div className="empty">
            Még nincs ilyen eset. Egy visszajelzésnél a „➕ Felvétel a mérésbe” gombbal a kérdés regressziós teszt lesz: a
            <code> run_all.py</code> (vagy <code>rag_eval.py</code> / <code>prompt_eval.py</code>) a kérdéssor mellett ezt is futtatja,
            így látszik, hogy a javítás működik-e, és egy későbbi változtatás nem rontja-e el újra.
          </div>
        ) : (
          <>
            {cases.items.map((c) => (
              <div key={c.id} className="case-row">
                <div className="case-row-head">
                  <b>{c.question}</b>
                  <button className="btn btn-sm btn-ghost push-right" onClick={() => remove(c.id)} title="Törlés">✕</button>
                </div>
                <div className="muted">Elvárás: {c.level === "rag"
                  ? `${c.doc_title ?? c.doc_file} · ${(c.pages ?? []).join(", ")}. o.`
                  : `${EXPECT_LABEL[c.expect ?? ""] ?? c.expect}${c.facts?.length ? ` – ${c.facts.join("; ")}` : ""}`}</div>
                <CaseCheck id={c.id} level={c.level} lastCheck={c.last_check} lastCheckAt={c.last_check_at}
                           busyExternal={runningId === c.id} onAuthError={onAuthError} onDone={onChanged} />
              </div>
            ))}
            <div className="fb-tools">
              <button className="btn btn-sm btn-primary" onClick={checkAll} disabled={runningId !== null} title={CHECK_HELP}>
                {runningId !== null ? `Ellenőrzés… (fb${runningId})` : `▶ Mind ellenőrzése (${cases.items.length})`}
              </button>
              {cases.yaml.rag && <button className="btn btn-sm" onClick={() => copy("rag")}>{copied === "rag" ? "Másolva ✓" : "RAG-esetek YAML-ja"}</button>}
              {cases.yaml.prompt && <button className="btn btn-sm" onClick={() => copy("prompt")}>{copied === "prompt" ? "Másolva ✓" : "Prompt-esetek YAML-ja"}</button>}
              <span className="muted">
                Végleges felvétel a git-be: másold a YAML-t az <code>eval/datasets/rag_questions.yaml</code> /
                <code> prompt_cases.yaml</code> végére, majd töröld itt az esetet (különben kétszer mérődik).
              </span>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
