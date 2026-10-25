import { useCallback, useEffect, useState } from "react";
import { fmtInt, fmtMs, fmtUsd, type Usage } from "../api";
import { adminFetch } from "./adminApi";
import { Kpi } from "./DocumentsTab";

const PURPOSE_LABEL: Record<string, string> = {
  chat: "válasz (stream)",
  rewrite: "kérdés-átírás",
  embed_query: "kérdés-embedding",
  rerank: "rerank",
  embed: "indexelés: embedding",
  vlm: "indexelés: képleírás (VLM)",
  metadata: "indexelés: metaadat",
  judge: "mérés: LLM-bíró",
  feedback_analysis: "visszajelzés-elemzés",
};
const isIngest = (p: string) => ["embed", "vlm", "metadata"].includes(p);

interface Resp {
  days: number;
  by_purpose: { purpose: string; model: string; calls: number; prompt_tokens: number; completion_tokens: number; cost_usd: number; avg_latency_ms: number; errors: number }[];
  by_day: { day: string; chat_cost: number | null; ingest_cost: number | null; tokens: number }[];
  latency: { answers: number; errors: number; ttft_p50: number | null; ttft_p95: number | null; total_p50: number | null; total_p95: number | null; avg_cost: number | null };
  recent: { id: string; created_at: string; usage: Usage | null; error: string | null; rating: string | null; question: string | null }[];
  phoenix_url: string | null;
}

export default function MonitoringTab({ onAuthError }: { onAuthError: (e: unknown) => void }) {
  const [days, setDays] = useState(7);
  const [data, setData] = useState<Resp | null>(null);
  const load = useCallback(() => {
    adminFetch<Resp>(`/api/admin/monitoring?days=${days}`).then(setData).catch(onAuthError);
  }, [days, onAuthError]);
  useEffect(load, [load]);

  if (!data) return <div className="page-loading">Betöltés…</div>;
  const L = data.latency;
  const chatCost = data.by_purpose.filter((p) => !isIngest(p.purpose)).reduce((a, p) => a + p.cost_usd, 0);
  const ingestCost = data.by_purpose.filter((p) => isIngest(p.purpose)).reduce((a, p) => a + p.cost_usd, 0);
  const tokens = data.by_purpose.reduce((a, p) => a + p.prompt_tokens + p.completion_tokens, 0);
  const maxDay = Math.max(0.000001, ...data.by_day.map((d) => (d.chat_cost ?? 0) + (d.ingest_cost ?? 0)));

  return (
    <div className="admin-grid">
      <div className="toolbar">
        <div className="seg small">
          {[1, 7, 30].map((d) => (
            <button key={d} className={days === d ? "on" : ""} onClick={() => setDays(d)}>{d === 1 ? "24 óra" : `${d} nap`}</button>
          ))}
        </div>
        <button className="btn btn-sm" onClick={load}>Frissítés</button>
        {data.phoenix_url && (
          <a className="btn btn-sm push-right" href={data.phoenix_url} target="_blank" rel="noreferrer">
            Phoenix trace-ek ↗
          </a>
        )}
      </div>

      <div className="kpis">
        <Kpi label="válasz" value={fmtInt(L.answers)} hint={`Ebből hibás: ${L.errors}`} />
        <Kpi label="első token (p50 / p95)" value={`${fmtMs(L.ttft_p50)} / ${fmtMs(L.ttft_p95)}`} />
        <Kpi label="teljes válaszidő (p50 / p95)" value={`${fmtMs(L.total_p50)} / ${fmtMs(L.total_p95)}`} />
        <Kpi label="átlagos költség / válasz" value={fmtUsd(L.avg_cost)} />
        <Kpi label="chat-költség" value={fmtUsd(chatCost)} />
        <Kpi label="indexelési költség" value={fmtUsd(ingestCost)} />
        <Kpi label="token összesen" value={fmtInt(tokens)} />
      </div>

      <div className="panel">
        <div className="panel-head"><h2>Napi költség</h2><span className="muted"><i className="lg chat" /> chat <i className="lg ingest" /> indexelés</span></div>
        <div className="panel-body">
          {data.by_day.length === 0 ? <div className="empty">Nincs adat.</div> : (
            <div className="day-bars">
              {data.by_day.map((d) => {
                const c = d.chat_cost ?? 0, g = d.ingest_cost ?? 0;
                return (
                  <div key={d.day} className="day" title={`${d.day}: chat ${fmtUsd(c)}, indexelés ${fmtUsd(g)}, ${fmtInt(d.tokens)} token`}>
                    <div className="day-stack">
                      <span className="ingest" style={{ height: `${(g / maxDay) * 100}%` }} />
                      <span className="chat" style={{ height: `${(c / maxDay) * 100}%` }} />
                    </div>
                    <span className="day-val">{fmtUsd(c + g)}</span>
                    <span className="muted">{d.day.slice(5)}</span>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </div>

      <div className="panel">
        <div className="panel-head"><h2>LLM-hívások célonként</h2></div>
        <div className="table-wrap">
          <table className="table">
            <thead><tr><th>Cél</th><th>Modell</th><th className="r">Hívás</th><th className="r">Input token</th><th className="r">Output token</th><th className="r">Költség</th><th className="r">Átl. idő</th><th className="r">Hiba</th></tr></thead>
            <tbody>
              {data.by_purpose.map((p) => (
                <tr key={p.purpose + p.model}>
                  <td>{PURPOSE_LABEL[p.purpose] ?? p.purpose}</td><td className="mono">{p.model}</td>
                  <td className="r">{fmtInt(p.calls)}</td><td className="r">{fmtInt(p.prompt_tokens)}</td><td className="r">{fmtInt(p.completion_tokens)}</td>
                  <td className="r">{fmtUsd(p.cost_usd)}</td><td className="r">{fmtMs(p.avg_latency_ms)}</td><td className="r">{p.errors || ""}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <div className="panel">
        <div className="panel-head"><h2>Legutóbbi válaszok</h2></div>
        <div className="table-wrap">
          <table className="table">
            <thead><tr><th>Időpont</th><th>Kérdés</th><th className="r">Első token</th><th className="r">Teljes</th><th className="r">Token</th><th className="r">Költség</th><th>Értékelés</th></tr></thead>
            <tbody>
              {data.recent.map((r) => (
                <tr key={r.id}>
                  <td className="nowrap">{new Date(r.created_at).toLocaleString("hu-HU")}</td>
                  <td>{r.question}{r.error && <div className="err-small">{r.error}</div>}</td>
                  <td className="r">{fmtMs(r.usage?.ttft_ms)}</td><td className="r">{fmtMs(r.usage?.total_ms)}</td>
                  <td className="r">{fmtInt((r.usage?.prompt_tokens ?? 0) + (r.usage?.completion_tokens ?? 0))}</td>
                  <td className="r">{fmtUsd(r.usage?.cost_usd)}</td>
                  <td>{r.rating === "up" ? "👍" : r.rating === "down" ? "👎" : ""}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
