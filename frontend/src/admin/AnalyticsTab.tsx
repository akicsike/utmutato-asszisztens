import { useCallback, useEffect, useState } from "react";
import { fmtInt, fmtMs, fmtUsd } from "../api";
import { adminFetch } from "./adminApi";
import { ChartCard, ColumnChart, dayLabel, HBarChart, LineChart, type Series } from "./charts";
import { Kpi } from "./DocumentsTab";
import { CaseCheck, EvalCaseForm, type EvalCaseRef } from "./evalCases";

type Row = Record<string, unknown>;

interface Resp {
  days: number;
  totals: { valaszok: number; nem_talalta_arany: number | null; ertekelt: number; elegedettseg: number | null };
  traffic: Row[];
  satisfaction: Row[];
  latency: Row[];
  latency_hist: Row[];
  score_hist: Row[];
  documents: Row[];
  cost: Row[];
  unanswered: { day: string; question: string | null }[];
  rerank_min_score: number;
}

// a kategória-színek fix sorrendben (dataviz-paletta), soha nem ciklikusan
const S = (i: number) => `var(--series-${i})`;
const TRAFFIC: Series[] = [
  { key: "valaszolt", label: "Válaszolt (forrással)", color: S(1) },
  { key: "nem_talalta", label: "„Nem találtam”", color: S(2) },
  { key: "egyeb", label: "Smalltalk / témán kívüli", color: S(3) },
  { key: "hiba", label: "Hiba", color: S(4) },
];
const LATENCY: Series[] = [
  { key: "atiras", label: "Kérdés-átírás", color: S(1) },
  { key: "kereses", label: "Keresés (embedding + BM25)", color: S(2) },
  { key: "rerank", label: "Rerank", color: S(3) },
  { key: "valasz", label: "Válasz-generálás", color: S(4) },
];
const COST: Series[] = [
  { key: "valasz", label: "Válasz", color: S(1) },
  { key: "atiras", label: "Átírás", color: S(2) },
  { key: "kereses", label: "Keresés (embedding, rerank)", color: S(3) },
  { key: "beolvasas", label: "Beolvasás (VLM, embedding)", color: S(4) },
  { key: "meres", label: "Mérés (LLM-bíró)", color: S(5) },
];

// a szűrő a böngésző-azonosító előtagja alapján dönt (backend: admin_insights.analytics, include_eval)
const TEST_TRAFFIC_HELP = [
  "Bekapcsolva a diagramok a gépi tesztforgalmat is mutatják; kikapcsolva csak a valódi felhasználók kérdéseit.",
  "",
  "Mérési és teszt-forgalom (azonosító eleje: eval- / smoke-):",
  "• alkalmazás-szintű mérés – 12 út, LLM-personás szimulált felhasználó (eval-app-…)",
  "• prompt-szintű mérés – 17 előre megírt, egyfordulós kérdés (eval-prompt-…)",
  "• Promptfoo funkcionális teszt és red team támadások (eval-promptfoo-…)",
  "• gyors kipróbáló tesztek (smoke-…)",
  "",
  "A RAG-szintű mérés nem jelenik meg itt: csak a keresést hívja, beszélgetést nem ment.",
  "Éles használatnál kapcsold ki – a tesztek sok elutasítást és „nem találtam” választ adnak.",
].join("\n");

const DAY_COL = { key: "day", label: "Nap", fmt: (v: unknown) => dayLabel(String(v)) };
const pct = (v: number) => `${Math.round(v * 100)} %`;
const pctOrDash = (v: unknown) => (typeof v === "number" ? pct(v) : "–");
const ms = (v: unknown) => fmtMs(typeof v === "number" ? v : null);
const usd = (v: unknown) => fmtUsd(typeof v === "number" ? v : null);
const sec = (v: number) => (v === 0 ? "0" : v >= 1000 ? `${(v / 1000).toLocaleString("hu-HU", { maximumFractionDigits: 1 })} s` : `${Math.round(v)} ms`);

export default function AnalyticsTab({ onAuthError }: { onAuthError: (e: unknown) => void }) {
  const [days, setDays] = useState(30);
  const [withEval, setWithEval] = useState(true);
  const [data, setData] = useState<Resp | null>(null);
  const [bucket, setBucket] = useState<number | null>(null);   // a „Keresési biztonság” kiválasztott oszlopa

  const load = useCallback(() => {
    adminFetch<Resp>(`/api/admin/analytics?days=${days}&include_eval=${withEval}`).then(setData).catch(onAuthError);
  }, [days, withEval, onAuthError]);
  useEffect(load, [load]);

  if (!data) return <div className="page-loading">Betöltés…</div>;
  const t = data.totals;
  const thr = data.rerank_min_score;

  return (
    <div className="admin-grid">
      <div className="toolbar">
        <div className="seg small">
          {[7, 30, 90].map((d) => (
            <button key={d} className={days === d ? "on" : ""} onClick={() => setDays(d)}>{d} nap</button>
          ))}
        </div>
        <label className="check has-help" title={TEST_TRAFFIC_HELP}>
          <input type="checkbox" checked={withEval} onChange={(e) => setWithEval(e.target.checked)} />
          mérési és teszt-forgalommal (nem valódi felhasználók)
        </label>
        <button className="btn btn-sm push-right" onClick={load}>Frissítés</button>
      </div>

      <div className="kpis">
        <Kpi label="válasz" value={fmtInt(t.valaszok)} />
        <Kpi label="„nem találtam” arány" value={pctOrDash(t.nem_talalta_arany)} warn={(t.nem_talalta_arany ?? 0) > 0.15} />
        <Kpi label="értékelt válasz" value={fmtInt(t.ertekelt)} />
        <Kpi label="elégedettség (👍 arány)" value={pctOrDash(t.elegedettseg)} />
      </div>

      <div className="chart-grid">
        <ChartCard
          title="Kérdések naponta és kimenetük"
          subtitle="Mennyi kérdés jön, és hányra nem volt forrás – a „nem találtam” a hiányzó / rosszul beolvasott útmutatót jelzi"
          series={TRAFFIC}
          table={{ columns: [DAY_COL, ...TRAFFIC.map((s) => ({ key: s.key, label: s.label }))], rows: data.traffic }}
        >
          <ColumnChart data={data.traffic} xKey="day" series={TRAFFIC} xFmt={dayLabel} fmt={(v) => fmtInt(v)} />
        </ChartCard>

        <ChartCard
          title="Elégedettség naponta"
          subtitle="A 👍 aránya az értékelt válaszokon belül – egy javítás (prompt, új útmutató) után ennek kell emelkednie"
          table={{ columns: [DAY_COL, { key: "rate", label: "👍 arány", fmt: pctOrDash },
                             { key: "up", label: "👍" }, { key: "down", label: "👎" }], rows: data.satisfaction }}
        >
          <LineChart data={data.satisfaction} xKey="day" yKey="rate" color={S(1)} fmt={pct} xFmt={dayLabel}
                     extra={(r) => <div className="tip-row">👍 {String(r.up)} · 👎 {String(r.down)}</div>} />
        </ChartCard>

        <ChartCard
          title="Válaszidő lépésenként (napi átlag)"
          subtitle="Hol megy el az idő egy válasznál – a legmagasabb szelet a gyorsítás iránya"
          series={LATENCY}
          table={{ columns: [DAY_COL, { key: "n", label: "Válasz" },
                             ...LATENCY.map((s) => ({ key: s.key, label: s.label, fmt: ms }))], rows: data.latency }}
        >
          <ColumnChart data={data.latency} xKey="day" series={LATENCY} xFmt={dayLabel} fmt={sec} />
        </ChartCard>

        <ChartCard
          title="Teljes válaszidő eloszlása"
          subtitle="Hány válasz készült el 1, 2, 3… másodperc alatt (forrással megválaszolt kérdések)"
          table={{ columns: [{ key: "bucket", label: "Idő" }, { key: "n", label: "Válasz" }], rows: data.latency_hist }}
        >
          <ColumnChart data={data.latency_hist} xKey="bucket" series={[{ key: "n", label: "Válasz", color: S(1) }]} fmt={(v) => fmtInt(v)} />
        </ChartCard>

        <ChartCard
          title="Keresési biztonság (a legjobb forrás rerank-pontja)"
          subtitle={<>A küszöb ({String(thr).replace(".", ",")}) alatti kérdésekre „nem találtam” a válasz; a küszöb közelében nagyobb a tévedés esélye</>}
          table={{ columns: [{ key: "bucket", label: "Pontszám" }, { key: "n", label: "Kérdés" }], rows: data.score_hist }}
        >
          <ColumnChart data={data.score_hist} xKey="bucket" series={[{ key: "n", label: "Kérdés", color: S(1) }]}
                       fmt={(v) => fmtInt(v)} refLine={{ between: thr * 10, label: "küszöb" }}
                       onSelect={(i) => setBucket((b) => (b === i ? null : i))} selected={bucket} />
          <div className="muted chart-foot">
            {bucket == null ? "Kattints egy oszlopra: alatta megjelennek a sáv kérdései." : "A sáv kérdései lent – újra kattintva bezárul."}
            {" "}A küszöb alatti („nem találtam”) kérdések nem itt, hanem a „Megválaszolatlan kérdések” listában vannak.
          </div>
        </ChartCard>

        {bucket != null && (
          <ScoreBucketList bucket={bucket} label={String(data.score_hist[bucket]?.bucket ?? "")} days={days} withEval={withEval}
                           thr={thr} onAuthError={onAuthError} onClose={() => setBucket(null)} />
        )}

        <ChartCard
          title="Kérdések útmutatónként"
          subtitle="Melyik útmutatóból válaszol a legtöbbször (hivatkozott forrás) – a tooltipben az értékelések"
          table={{ columns: [{ key: "title", label: "Útmutató" }, { key: "kerdes", label: "Kérdés" }, { key: "up", label: "👍" }, { key: "down", label: "👎" }],
                   rows: data.documents }}
        >
          <HBarChart data={data.documents} labelKey="title" valueKey="kerdes" color={S(1)}
                     extra={(r) => <>👍 {String(r.up)} · 👎 {String(r.down)}</>} />
        </ChartCard>

        <ChartCard
          title="Költség naponta, célonként (USD)"
          subtitle="A teljes OpenRouter-költség: a beolvasás egyszeri, a válasz és a keresés a forgalommal nő"
          series={COST}
          table={{ columns: [DAY_COL, ...COST.map((s) => ({ key: s.key, label: s.label, fmt: usd }))], rows: data.cost }}
        >
          <ColumnChart data={data.cost} xKey="day" series={COST} xFmt={dayLabel} fmt={(v) => fmtUsd(v)} />
        </ChartCard>

        <div className="panel chart-card">
          <div className="chart-head"><div><h3>Megválaszolatlan kérdések</h3>
            <div className="muted">A legutóbbi „nem találtam” válaszok – ezekhez hiányzik vagy rosszul olvasódott be az útmutató</div></div></div>
          {data.unanswered.length === 0 ? (
            <div className="chart-empty">Nincs megválaszolatlan kérdés a kiválasztott időszakban.</div>
          ) : (
            <ul className="unanswered">
              {data.unanswered.map((u, i) => (
                <li key={i}><span className="muted">{dayLabel(u.day)}</span> {u.question ?? "–"}</li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </div>
  );
}

// ------------------------------------------------------------------ „Keresési biztonság” → egy sáv kérdései

interface BucketItem {
  message_id: string;
  created_at: string;
  question: string | null;
  search_query: string | null;
  answer: string;
  top_score: number;
  best_source: { title: string; document_id: number; page_from: number | null; page_to: number | null; section: string | null; pdf_url: string | null };
  n_sources: number;
  cited_best: boolean;
  rating: "up" | "down" | null;
  reasons: string[];
  comment: string | null;
  error: string | null;
  test_traffic: boolean;
  trace_url: string | null;
  eval_cases: EvalCaseRef[];
}

const score2 = (v: number) => v.toFixed(3).replace(".", ",");

function ScoreBucketList({ bucket, label, days, withEval, thr, onAuthError, onClose }: {
  bucket: number; label: string; days: number; withEval: boolean; thr: number;
  onAuthError: (e: unknown) => void; onClose: () => void;
}) {
  const [items, setItems] = useState<BucketItem[] | null>(null);
  const load = useCallback(() => {
    adminFetch<{ items: BucketItem[] }>(`/api/admin/analytics/score-bucket?bucket=${bucket}&days=${days}&include_eval=${withEval}`)
      .then((r) => setItems(r.items)).catch(onAuthError);
  }, [bucket, days, withEval, onAuthError]);
  useEffect(() => { setItems(null); load(); }, [load]);

  return (
    <div className="panel chart-card bucket-list">
      <div className="chart-head">
        <div>
          <h3>A {label} sáv kérdései{items ? ` (${items.length})` : ""}</h3>
          <div className="muted">A legjobb forrás rerank-pontja szerint növekvő sorrendben – a küszöbhöz ({String(thr).replace(".", ",")}) legközelebbiek elöl.
            {withEval ? " A mérési és teszt-forgalom is benne van (szűrő fent)." : ""}</div>
        </div>
        <button className="btn btn-sm btn-ghost" onClick={onClose}>Bezárás ✕</button>
      </div>
      {!items ? <div className="chart-empty">Betöltés…</div>
        : items.length === 0 ? <div className="chart-empty">Ebben a sávban nincs kérdés.</div>
        : items.map((it) => <BucketRow key={it.message_id} it={it} thr={thr} onAuthError={onAuthError} onChanged={load} />)}
    </div>
  );
}

function BucketRow({ it, thr, onAuthError, onChanged }: {
  it: BucketItem; thr: number; onAuthError: (e: unknown) => void; onChanged: () => void;
}) {
  const [formOpen, setFormOpen] = useState(false);
  const s = it.best_source;
  const pages = s.page_from == null ? "" : s.page_to && s.page_to !== s.page_from ? `${s.page_from}–${s.page_to}. o.` : `${s.page_from}. o.`;
  const outcome = it.error ? "hiba" : it.answer.startsWith("Erről nem találtam") ? "„nem találtam”" : "válaszolt";
  return (
    <div className="bucket-row">
      <div className="bucket-row-head">
        <span className={`check-badge ${it.top_score < thr + 0.1 ? "bad" : "ok"}`} title="A legjobb forrás rerank-pontja (0–1)">{score2(it.top_score)}</span>
        <b>{it.question ?? "(kérdés nem található)"}</b>
        {it.rating && <span title={it.reasons.length ? it.reasons.join(", ") : undefined}>{it.rating === "up" ? "👍" : "👎"}</span>}
        {it.test_traffic && <span className="tag" title="Mérési / teszt-forgalom (eval- / smoke- azonosító)">teszt</span>}
        <span className="muted push-right">{new Date(it.created_at).toLocaleString("hu-HU")} · {outcome}</span>
      </div>
      {it.search_query && it.search_query !== it.question && (
        <div className="muted">Keresőkérdés (átírás után): <i>{it.search_query}</i></div>
      )}
      <div className="muted">
        Legjobb forrás: <b>{s.title}</b>{s.section ? ` · ${s.section}` : ""} · {s.pdf_url ? <a href={s.pdf_url} target="_blank" rel="noreferrer">{pages} ↗</a> : pages}
        {it.cited_best ? " · a válasz hivatkozik rá" : " · a válasz nem hivatkozik rá"} · {it.n_sources} forrás
      </div>
      {it.comment && <div className="fb-comment">„{it.comment}”</div>}
      <details>
        <summary className="muted">Válasz</summary>
        <div className="fb-answer">{it.answer}</div>
      </details>
      <div className="fb-tools">
        {it.trace_url && (
          <a className="btn btn-sm" href={it.trace_url} target="_blank" rel="noreferrer"
             title="A válasz nyoma a Phoenixben: átírás → keresés → rerank-pontok → LLM-hívás">🔎 Phoenix-trace ↗</a>
        )}
        <button className="btn btn-sm" onClick={() => setFormOpen((v) => !v)}>{formOpen ? "Mégse" : "➕ Felvétel a mérésbe"}</button>
      </div>
      {it.eval_cases.map((c) => (
        <CaseCheck key={c.id} id={c.id} level={c.level} lastCheck={c.last_check} lastCheckAt={c.last_check_at}
                   onAuthError={onAuthError} onDone={onChanged} />
      ))}
      {formOpen && (
        <EvalCaseForm messageId={it.message_id} question={it.question} docId={s.document_id} facts={it.comment}
                      onAuthError={onAuthError} onSaved={() => { setFormOpen(false); onChanged(); }} />
      )}
    </div>
  );
}
