// Mérési esetek egy válaszból: „➕ Felvétel a mérésbe” űrlap és „▶ Ellenőrzés most” (eval/quick_check.py).
// A Visszajelzések és az Analitika fül (keresési biztonság → kérdéslista) is ezt használja.
import { useEffect, useState } from "react";
import { adminFetch, type DocRow } from "./adminApi";

const num2 = (v: number) => v.toFixed(2).replace(".", ",");

/** A válaszhoz tartozó mérési eset (a lista-végpontok json_agg-ja adja). */
export interface EvalCaseRef {
  id: number;
  level: "rag" | "prompt";
  last_check: CheckResult | null;
  last_check_at: string | null;
}

let docsCache: Promise<DocRow[]> | null = null;   // az útmutató-lista lapbetöltésenként egyszer

export function EvalCaseForm({ messageId, question: q0, docId, facts: facts0, onAuthError, onSaved }: {
  messageId: string; question: string | null; docId?: number | null; facts?: string | null;
  onAuthError: (e: unknown) => void; onSaved: () => void;
}) {
  const [docs, setDocs] = useState<DocRow[]>([]);
  const [level, setLevel] = useState<"rag" | "prompt">("rag");
  const [question, setQuestion] = useState(q0 ?? "");
  const [docFile, setDocFile] = useState("");
  const [pageText, setPageText] = useState("");
  const [expect, setExpect] = useState("answer");
  const [facts, setFacts] = useState(facts0 ?? "");
  const [err, setErr] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    docsCache ??= adminFetch<{ documents: DocRow[] }>("/api/admin/documents").then((r) => r.documents);
    docsCache.then((d) => {
      setDocs(d);
      // előtöltés: a hivatkozott (vagy a legjobb) forrás útmutatója
      const doc = d.find((x) => x.id === docId);
      if (doc) setDocFile((cur) => cur || doc.filename);
    }).catch((e) => { docsCache = null; onAuthError(e); });
  }, [docId, onAuthError]);

  async function save() {
    setErr(null);
    const pageList = pageText.split(/[,;\s]+/).filter(Boolean).flatMap((p) => {
      const m = p.match(/^(\d+)[-–](\d+)$/);
      if (m) return Array.from({ length: Math.max(0, +m[2] - +m[1] + 1) }, (_, i) => +m[1] + i);
      return [Number(p)];
    });
    if (level === "rag" && (pageList.length === 0 || pageList.some((p) => !Number.isInteger(p) || p < 1))) {
      setErr("Az oldalszámokat számként add meg, pl. „34, 35” vagy „34-35”.");
      return;
    }
    setSaving(true);
    try {
      await adminFetch("/api/admin/eval-cases", {
        method: "POST",
        body: JSON.stringify({
          message_id: messageId, level, question,
          doc_file: level === "rag" ? docFile : null, pages: level === "rag" ? pageList : null,
          expect: level === "prompt" ? expect : null,
          facts: level === "prompt" ? facts.split("\n").map((f) => f.trim()).filter(Boolean) : null,
        }),
      });
      onSaved();
    } catch (e) {
      onAuthError(e);
      setErr((e as Error).message);
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="eval-form">
      <div className="seg small">
        <button className={level === "rag" ? "on" : ""} onClick={() => setLevel("rag")}
                title="A keresést méri: megtalálja-e a helyes útmutató-oldalt (precision / recall / MRR)">RAG – keresés</button>
        <button className={level === "prompt" ? "on" : ""} onClick={() => setLevel("prompt")}
                title="A választ méri LLM-bíróval: helyesség, hallucináció, elvárt viselkedés">Prompt – válasz</button>
      </div>
      <label>Kérdés<input value={question} onChange={(e) => setQuestion(e.target.value)} /></label>
      {level === "rag" ? (
        <>
          <label>Elvárt útmutató
            <select value={docFile} onChange={(e) => setDocFile(e.target.value)}>
              <option value="">– válassz –</option>
              {docs.map((d) => <option key={d.id} value={d.filename}>{d.title}</option>)}
            </select>
          </label>
          <label>Oldal(ak), ahol a válasz van<input value={pageText} placeholder="pl. 34, 35 vagy 34-35" onChange={(e) => setPageText(e.target.value)} /></label>
          <div className="muted">Tipp: a PDF-ben nézd meg, melyik oldalon van a helyes válasz – a mérés azt nézi, ez az oldal bekerül-e a 6 találat közé.</div>
        </>
      ) : (
        <>
          <label>Elvárt viselkedés
            <select value={expect} onChange={(e) => setExpect(e.target.value)}>
              {Object.entries(EXPECT_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            </select>
          </label>
          <label>A helyes válasz kulcselemei (soronként egy)
            <textarea rows={3} value={facts} placeholder="pl. 0 és +45 °C között kell tölteni" onChange={(e) => setFacts(e.target.value)} />
          </label>
        </>
      )}
      {err && <div className="notice bad">{err}</div>}
      <div className="fb-actions">
        <button className="btn btn-primary btn-sm" onClick={save} disabled={saving || question.trim().length < 3 || (level === "rag" && !docFile)}>
          {saving ? "Mentés…" : "Mentés mérési esetként"}
        </button>
      </div>
    </div>
  );
}

export const EXPECT_LABEL: Record<string, string> = {
  answer: "válaszol (a forrásból)",
  not_found: "„nem találtam” (nincs benne)",
  refuse: "elutasít (témán kívüli)",
  clarify: "visszakérdez (kétértelmű)",
};

export interface CheckHit {
  rank: number | null;
  title: string;
  page_from: number | null;
  page_to: number | null;
  section: string | null;
  kind: string;
  score: number | null;
  relevant: boolean;
}

/** Az „▶ Ellenőrzés most” eredménye (eval/quick_check.py). */
export interface CheckResult {
  level: "rag" | "prompt";
  ok: boolean;
  error?: string;
  ms?: number;
  // RAG
  rank?: number | null;
  n_hits?: number;
  expected?: string;
  query?: string;
  keywords?: string[];
  hits?: CheckHit[];
  weak?: CheckHit[];
  // prompt
  expect?: string;
  behavior?: string;
  behavior_ok?: boolean;
  correctness?: number | null;
  hallucination?: number | null;
  unsupported_claims?: string[];
  n_sources?: number;
  answer?: string;
  judge_explanation?: string;
  cost_usd?: number | null;
}

export const CHECK_HELP =
  "Csak ezt az esetet futtatja le, most – a teljes mérés nélkül.\n" +
  "RAG-eset: az éles keresés, ahogy a chat keres (kérdés-átírás + kulcsszavak, hibrid + rerank + küszöb), és hányadik " +
  "helyen jön az elvárt oldal. Pár másodperc, < 0,01 $.\n" +
  "Prompt-eset: a teljes válasz + a két LLM-bíró, mint a prompt_eval.py-ban. Kb. 10–20 másodperc, kb. 0,003 $.\n" +
  "Az eredmény az esethez mentődik; a teljes mérés (rag_eval.py) ettől kicsit eltérhet, mert ott átírás és küszöb nélkül fut.";

export function checkSummary(r: CheckResult): string {
  if (r.error) return `hiba: ${r.error}`;
  if (r.level === "rag") {
    if (r.ok) return `a jó oldal a ${r.rank}. helyen (${r.n_hits} találatból)`;
    return r.n_hits ? `a jó oldal nincs a ${r.n_hits} találat között` : "nincs találat a küszöb felett („nem találtam”)";
  }
  const parts = [
    r.behavior_ok ? "elvárt viselkedés" : `rossz viselkedés (${EXPECT_LABEL[r.behavior ?? ""] ?? r.behavior})`,
    r.correctness != null ? `helyesség ${num2(r.correctness)}` : null,
    r.hallucination == null ? null : r.hallucination ? "hallucinált" : "forráshű",
  ];
  return parts.filter(Boolean).join(" · ");
}

export function HitTable({ hits }: { hits: CheckHit[] }) {
  return (
    <table className="fb-src">
      <thead><tr><th>#</th><th>Találat</th><th>Oldal</th><th>Rerank</th><th title="Az elvárt útmutató elvárt oldala-e">Jó?</th></tr></thead>
      <tbody>
        {hits.map((h, i) => (
          <tr key={i} className={h.relevant ? "cited" : ""}>
            <td>{h.rank ?? "–"}</td>
            <td>{h.title}{h.kind === "image" && <span className="tag">kép</span>}{h.section && <div className="muted">{h.section}</div>}</td>
            <td>{h.page_from == null ? "" : h.page_to && h.page_to !== h.page_from ? `${h.page_from}–${h.page_to}.` : `${h.page_from}.`}</td>
            <td>{h.score == null ? "–" : num2(h.score)}</td>
            <td>{h.relevant ? "✓" : ""}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export function CaseCheck({ id, level, lastCheck, lastCheckAt, busyExternal, onAuthError, onDone }: {
  id: number; level: "rag" | "prompt"; lastCheck: CheckResult | null; lastCheckAt: string | null; busyExternal?: boolean;
  onAuthError: (e: unknown) => void; onDone: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const running = busy || !!busyExternal;

  async function run() {
    setBusy(true);
    setErr(null);
    try {
      await adminFetch(`/api/admin/eval-cases/${id}/check`, { method: "POST" });
      onDone();
    } catch (e) {
      onAuthError(e);
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const r = lastCheck;
  return (
    <div className="case-check">
      <div className="case-check-row">
        <span className="tag cite" title="Mérési eset – a következő teljes mérés is futtatja">📏 fb{id} · {level === "rag" ? "RAG" : "Prompt"}</span>
        {r ? (
          <span className={`check-badge ${r.ok ? "ok" : "bad"}`}>{r.ok ? "✓" : "✗"} {checkSummary(r)}</span>
        ) : (
          <span className="muted">még nem ellenőrizve</span>
        )}
        {lastCheckAt && <span className="muted">{new Date(lastCheckAt).toLocaleString("hu-HU")}</span>}
        <button className="btn btn-sm" onClick={run} disabled={running} title={CHECK_HELP}>
          {running ? "Ellenőrzés…" : "▶ Ellenőrzés most"}
        </button>
      </div>
      {err && <div className="notice bad">{err}</div>}
      {r && !r.error && (
        <details>
          <summary className="muted">Részletek</summary>
          {r.level === "rag" ? (
            <div className="case-check-body">
              <div className="muted">Elvárt: <b>{r.expected}</b></div>
              <div className="muted">Keresőkérdés: <i>{r.query}</i>{r.keywords?.length ? ` · kulcsszavak: ${r.keywords.join(", ")}` : ""}</div>
              {(r.hits ?? []).length > 0 ? <HitTable hits={r.hits!} /> : (
                <>
                  <div className="muted">Egyik találat sem érte el a küszöböt. A legközelebbi jelöltek:</div>
                  <HitTable hits={r.weak ?? []} />
                </>
              )}
            </div>
          ) : (
            <div className="case-check-body">
              <div className="muted">Elvárt viselkedés: <b>{EXPECT_LABEL[r.expect ?? ""] ?? r.expect}</b> · a válasz: {EXPECT_LABEL[r.behavior ?? ""] ?? r.behavior} · {r.n_sources} forrás{r.cost_usd != null ? ` · $${r.cost_usd.toFixed(4)}` : ""}</div>
              <div className="fb-answer">{r.answer}</div>
              {(r.unsupported_claims ?? []).length > 0 && (
                <div className="fb-hint">Alátámasztatlan állítás: {r.unsupported_claims!.join("; ")}</div>
              )}
              {r.judge_explanation && <div className="muted">A bíró: {r.judge_explanation}</div>}
            </div>
          )}
        </details>
      )}
    </div>
  );
}
