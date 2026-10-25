import { Fragment, useCallback, useEffect, useState } from "react";
import { adminFetch } from "./adminApi";
import { Kpi } from "./DocumentsTab";
import { metricHelp } from "./metricHelp";

// eval_runs.summary formátuma (az eval/ szkriptek így mentik):
//   { metrics: {név: szám}, table?: [{...sor}], notes?: string }
interface Summary {
  metrics?: Record<string, number | string | null>;
  table?: Record<string, unknown>[];
  notes?: string;
}

interface Run {
  id: number;
  level: "rag" | "prompt" | "app";
  name: string;
  config: Record<string, unknown> | null;
  summary: Summary | null;
  created_at: string;
  results?: Record<string, unknown>[];
}

const LEVEL_LABEL = { rag: "RAG-szint", prompt: "Prompt-szint", app: "Alkalmazás-szint" };

const fmtVal = (v: unknown): string => {
  if (v == null) return "–";
  if (typeof v === "number") return Number.isInteger(v) ? String(v) : v.toFixed(3).replace(".", ",");
  if (typeof v === "boolean") return v ? "✔" : "✘";
  if (typeof v === "object") return JSON.stringify(v);
  return String(v);
};

export default function EvalTab({ onAuthError }: { onAuthError: (e: unknown) => void }) {
  const [runs, setRuns] = useState<Run[]>([]);
  const [open, setOpen] = useState<Run | null>(null);

  const load = useCallback(() => {
    adminFetch<{ runs: Run[] }>("/api/admin/eval-runs").then((r) => setRuns(r.runs)).catch(onAuthError);
  }, [onAuthError]);
  useEffect(load, [load]);

  const openRun = (id: number) => adminFetch<Run>(`/api/admin/eval-runs/${id}`).then(setOpen).catch(onAuthError);

  // szintenként a legutóbbi futás felül
  const latest = (["rag", "prompt", "app"] as const).map((lv) => runs.find((r) => r.level === lv)).filter(Boolean) as Run[];

  return (
    <div className="admin-grid">
      {runs.length === 0 && (
        <div className="panel"><div className="panel-body empty">
          Még nincs mérés. A mérések a WSL-ben futnak: <code>docker compose exec api python /eval/run_all.py</code> – az eredmény ide kerül.
        </div></div>
      )}
      {latest.map((r) => (
        <div key={r.id} className="panel">
          <div className="panel-head">
            <h2>{LEVEL_LABEL[r.level]}</h2>
            <b>{r.name}</b>
            <span className="muted">{new Date(r.created_at).toLocaleString("hu-HU")}</span>
            <button className="btn btn-sm push-right" onClick={() => openRun(r.id)}>Esetek</button>
          </div>
          <div className="panel-body">
            {r.summary?.metrics && (
              <div className="kpis">
                {Object.entries(r.summary.metrics).map(([k, v]) => <Kpi key={k} label={k} value={fmtVal(v)} />)}
              </div>
            )}
            {r.summary?.table && <DataTable rows={r.summary.table} />}
            {r.summary?.notes && <p className="muted">{r.summary.notes}</p>}
          </div>
        </div>
      ))}

      {runs.length > 0 && (
        <div className="panel">
          <div className="panel-head"><h2>Összes futás</h2></div>
          <div className="table-wrap">
            <table className="table">
              <thead><tr><th>#</th><th>Szint</th><th>Név</th><th>Időpont</th><th /></tr></thead>
              <tbody>
                {runs.map((r) => (
                  <tr key={r.id}>
                    <td>{r.id}</td><td>{LEVEL_LABEL[r.level]}</td><td>{r.name}</td>
                    <td>{new Date(r.created_at).toLocaleString("hu-HU")}</td>
                    <td><button className="btn btn-sm" onClick={() => openRun(r.id)}>Részletek</button></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {open && (
        <div className="drawer-backdrop" onClick={() => setOpen(null)}>
          <aside className="drawer right wide" onClick={(e) => e.stopPropagation()}>
            <div className="drawer-head">
              <div><h2>{LEVEL_LABEL[open.level]} · #{open.id}</h2><b>{open.name}</b></div>
              <button className="btn btn-ghost" onClick={() => setOpen(null)} aria-label="Bezárás">✕</button>
            </div>
            <div className="drawer-scroll">
              {open.config && <pre className="json">{JSON.stringify(open.config, null, 2)}</pre>}
              <DataTable rows={open.results ?? []} expandable />
            </div>
          </aside>
        </div>
      )}
    </div>
  );
}

function DataTable({ rows, expandable }: { rows: Record<string, unknown>[]; expandable?: boolean }) {
  const [exp, setExp] = useState<number | null>(null);
  if (!rows.length) return <div className="empty">Nincs adat.</div>;
  const cols = [...new Set(rows.flatMap((r) => Object.keys(r)))].filter(
    (c) => rows.every((r) => typeof r[c] !== "object" || r[c] == null)).slice(0, 12);
  return (
    <div className="table-wrap">
      <table className="table compact">
        <thead><tr>{cols.map((c) => {
          const help = metricHelp(c);
          return <th key={c} title={help} className={help ? "has-help" : ""}>{c}</th>;
        })}</tr></thead>
        <tbody>
          {rows.map((r, i) => (
            <Fragment key={i}>
              <tr className={expandable ? "clickable" : ""} onClick={() => expandable && setExp(exp === i ? null : i)}>
                {cols.map((c) => <td key={c} className={typeof r[c] === "number" ? "r" : ""}>{fmtVal(r[c]).slice(0, 160)}</td>)}
              </tr>
              {expandable && exp === i && (
                <tr><td colSpan={cols.length}><pre className="json">{JSON.stringify(r, null, 2)}</pre></td></tr>
              )}
            </Fragment>
          ))}
        </tbody>
      </table>
    </div>
  );
}
