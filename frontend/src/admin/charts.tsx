// SVG-diagramok az admin Analitika fülhöz. A d3 adja a matematikát (skálák, "szép" tengelyosztás, halmozás,
// vonal- és terület-generátor), a rajzolást a React végzi – így a d3 nem nyúl a DOM-hoz, nem ütközik a Reacttel.
// Dataviz-irányelvek: vékony oszlopok (max 24 px), 4 px lekerekített adatvég, 2 px felületrés a halmozott szeletek
// között, 2 px vonal, hairline rács, hover-tooltip, jelmagyarázat >= 2 sorozatnál, táblázat-nézet minden diagramhoz.
import { max as d3max } from "d3-array";
import { scaleBand, scaleLinear } from "d3-scale";
import { area, curveMonotoneX, line, stack } from "d3-shape";
import { useEffect, useRef, useState, type ReactNode } from "react";

export interface Series {
  key: string;
  label: string;
  color: string; // CSS-változó, pl. "var(--series-1)"
}

type Row = Record<string, unknown>;

function useWidth<T extends HTMLElement>(): [React.RefObject<T>, number] {
  const ref = useRef<T>(null);
  const [w, setW] = useState(600);
  useEffect(() => {
    if (!ref.current) return;
    const ro = new ResizeObserver(([e]) => setW(Math.max(240, Math.floor(e.contentRect.width))));
    ro.observe(ref.current);
    return () => ro.disconnect();
  }, []);
  return [ref, w];
}

const num = (r: Row, k: string) => (typeof r[k] === "number" ? (r[k] as number) : 0);

/** "2026-10-25" -> "10.25." */
export const dayLabel = (d: string) => (/^\d{4}-\d{2}-\d{2}$/.test(d) ? `${d.slice(5, 7)}.${d.slice(8, 10)}.` : d);

// ------------------------------------------------------------------ keret

export function ChartCard({ title, subtitle, series, table, children }: {
  title: string; subtitle?: ReactNode; series?: Series[]; table?: { columns: { key: string; label: string; fmt?: (v: unknown) => string }[]; rows: Row[] };
  children: ReactNode;
}) {
  const [showTable, setShowTable] = useState(false);
  return (
    <div className="panel chart-card">
      <div className="chart-head">
        <div>
          <h3>{title}</h3>
          {subtitle && <div className="muted">{subtitle}</div>}
        </div>
        {table && (
          <button className="btn btn-sm btn-ghost" onClick={() => setShowTable((s) => !s)} aria-pressed={showTable}>
            {showTable ? "Diagram" : "Táblázat"}
          </button>
        )}
      </div>
      {series && series.length > 1 && (
        <div className="legend">
          {series.map((s) => (
            <span key={s.key}><i style={{ background: s.color }} />{s.label}</span>
          ))}
        </div>
      )}
      {showTable && table ? (
        <div className="table-wrap chart-table">
          <table className="table compact">
            <thead><tr>{table.columns.map((c) => <th key={c.key}>{c.label}</th>)}</tr></thead>
            <tbody>
              {table.rows.map((r, i) => (
                <tr key={i}>{table.columns.map((c) => (
                  <td key={c.key} className={typeof r[c.key] === "number" ? "r" : ""}>
                    {c.fmt ? c.fmt(r[c.key]) : r[c.key] == null ? "–" : String(r[c.key])}
                  </td>
                ))}</tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        children
      )}
    </div>
  );
}

function Tooltip({ x, y, w, children }: { x: number; y: number; w: number; children: ReactNode }) {
  const left = Math.min(Math.max(x + 12, 4), w - 190);
  return <div className="chart-tip" style={{ left, top: Math.max(0, y - 10) }}>{children}</div>;
}

const PAD = { l: 44, r: 12, t: 12, b: 28 };

// ------------------------------------------------------------------ oszlop / halmozott oszlop

export function ColumnChart({ data, xKey, series, fmt = (v) => String(v), xFmt = (v) => v, height = 220, refLine, empty,
                              onSelect, selected }: {
  data: Row[]; xKey: string; series: Series[]; fmt?: (v: number) => string; xFmt?: (v: string) => string;
  height?: number; refLine?: { between: number; label: string }; empty?: string;
  /** ha meg van adva, az oszlop kattintható (pl. a sáv kérdéseinek listájához); a kiválasztott oszlop kiemelve */
  onSelect?: (i: number) => void; selected?: number | null;
}) {
  const [ref, w] = useWidth<HTMLDivElement>();
  const [hover, setHover] = useState<number | null>(null);
  if (!data.length) return <div className="chart-empty">{empty ?? "Nincs adat a kiválasztott időszakban."}</div>;
  const ih = height - PAD.t - PAD.b;
  const keys = series.map((s) => s.key);
  // d3.stack: soronként a sorozatok [alsó, felső] határai -> halmozott oszlop
  const layers = stack<Row>().keys(keys).value((r, k) => num(r, k))(data);
  const totals = data.map((r) => keys.reduce((a, k) => a + num(r, k), 0));
  const x = scaleBand<number>().domain(data.map((_, i) => i)).range([PAD.l, w - PAD.r]).paddingInner(0.25);
  const y = scaleLinear().domain([0, d3max(totals) || 1]).nice().range([PAD.t + ih, PAD.t]);
  const band = x.step();
  const bw = Math.min(24, x.bandwidth());
  const cx = (i: number) => (x(i) ?? 0) + x.bandwidth() / 2;
  const labelEvery = Math.ceil(data.length / Math.max(1, Math.floor((w - PAD.l - PAD.r) / 56)));
  // a referenciavonal a két szomszédos oszlop közötti rés közepére kerül
  // (törtszám is lehet: 1,5 = a 2. oszlop közepe)
  const refX = refLine
    ? (x(Math.floor(refLine.between)) ?? w - PAD.r) - (band - x.bandwidth()) / 2 + (refLine.between % 1) * band
    : 0;

  return (
    <div className="chart" ref={ref} onMouseLeave={() => setHover(null)}>
      <svg width={w} height={height} role="img">
        {y.ticks(4).map((t) => (
          <g key={t}>
            <line x1={PAD.l} x2={w - PAD.r} y1={y(t)} y2={y(t)} className={t === 0 ? "axis" : "grid"} />
            <text x={PAD.l - 6} y={y(t) + 4} className="tick" textAnchor="end">{fmt(t)}</text>
          </g>
        ))}
        {data.map((r, i) => {
          // a sávon belül a legfelső nem nulla szelet kapja a lekerekített végét
          const segs = layers.map((L, j) => ({ s: series[j], lo: L[i][0], hi: L[i][1] })).filter((g) => g.hi > g.lo);
          const focus = hover ?? selected ?? null;
          return (
            <g key={i} opacity={focus == null || focus === i ? 1 : 0.55}>
              {segs.map(({ s, lo, hi }, j) => {
                const yTop = y(hi);
                const h = Math.max(0, y(lo) - yTop - (j > 0 ? 2 : 0)); // 2 px felületrés a szeletek között
                return j === segs.length - 1
                  ? <path key={s.key} fill={s.color} d={roundTop(cx(i) - bw / 2, yTop, bw, h, Math.min(4, h))} />
                  : <rect key={s.key} fill={s.color} x={cx(i) - bw / 2} y={yTop} width={bw} height={h} />;
              })}
              {i % labelEvery === 0 && (
                <text x={cx(i)} y={height - 8} className="tick" textAnchor="middle">{xFmt(String(r[xKey]))}</text>
              )}
              <rect x={cx(i) - band / 2} y={PAD.t} width={band} height={ih} fill="transparent"
                    onMouseMove={() => setHover(i)}
                    {...(onSelect && totals[i] > 0 ? { onClick: () => onSelect(i), style: { cursor: "pointer" } } : {})} />
            </g>
          );
        })}
        {refLine && (
          <g>
            <line x1={refX} x2={refX} y1={PAD.t} y2={PAD.t + ih} className="ref" />
            <text x={refX + 4} y={PAD.t + 10} className="tick">{refLine.label}</text>
          </g>
        )}
      </svg>
      {hover != null && (
        <Tooltip x={cx(hover)} y={y(totals[hover])} w={w}>
          <b>{xFmt(String(data[hover][xKey]))}</b>
          {series.map((s) => (
            <div key={s.key} className="tip-row"><i style={{ background: s.color }} />{s.label}<span>{fmt(num(data[hover], s.key))}</span></div>
          ))}
          {series.length > 1 && <div className="tip-row total">Összesen<span>{fmt(totals[hover])}</span></div>}
        </Tooltip>
      )}
    </div>
  );
}

function roundTop(x: number, y: number, w: number, h: number, r: number): string {
  if (h <= 0) return "";
  return `M${x},${y + h} V${y + r} Q${x},${y} ${x + r},${y} H${x + w - r} Q${x + w},${y} ${x + w},${y + r} V${y + h} Z`;
}

// ------------------------------------------------------------------ vonal (egy sorozat)

export function LineChart({ data, xKey, yKey, color, fmt, xFmt = (v) => v, max = 1, height = 220, extra }: {
  data: Row[]; xKey: string; yKey: string; color: string; fmt: (v: number) => string; xFmt?: (v: string) => string;
  max?: number; height?: number; extra?: (r: Row) => ReactNode;
}) {
  const [ref, w] = useWidth<HTMLDivElement>();
  const [hover, setHover] = useState<number | null>(null);
  const pts = data.map((r, i) => ({ r, i, v: typeof r[yKey] === "number" ? (r[yKey] as number) : null }));
  if (!pts.some((p) => p.v != null)) return <div className="chart-empty">Még nincs értékelés a kiválasztott időszakban.</div>;
  const iw = w - PAD.l - PAD.r, ih = height - PAD.t - PAD.b;
  const xs = scaleLinear().domain(data.length > 1 ? [0, data.length - 1] : [-1, 1]).range([PAD.l, w - PAD.r]);
  const y = scaleLinear().domain([0, max]).range([PAD.t + ih, PAD.t]);
  const x = (i: number) => xs(i);
  const step = data.length > 1 ? iw / (data.length - 1) : 0;
  const valid = pts.filter((p) => p.v != null) as { r: Row; i: number; v: number }[];
  // d3.line / d3.area: a hiányzó napok (nincs értékelés) kimaradnak, a görbe monoton marad (nem lő túl 100 %-on)
  const path = line<{ i: number; v: number }>().x((p) => x(p.i)).y((p) => y(p.v)).curve(curveMonotoneX)(valid) ?? "";
  const wash = area<{ i: number; v: number }>().x((p) => x(p.i)).y0(y(0)).y1((p) => y(p.v)).curve(curveMonotoneX)(valid) ?? "";
  const ticks = y.ticks(4);
  const labelEvery = Math.ceil(data.length / Math.max(1, Math.floor(iw / 56)));
  return (
    <div className="chart" ref={ref} onMouseLeave={() => setHover(null)}
         onMouseMove={(e) => {
           const bx = e.currentTarget.getBoundingClientRect().left;
           const i = Math.round((e.clientX - bx - PAD.l) / (step || 1));
           setHover(Math.max(0, Math.min(data.length - 1, i)));
         }}>
      <svg width={w} height={height} role="img">
        {ticks.map((t) => (
          <g key={t}>
            <line x1={PAD.l} x2={w - PAD.r} y1={y(t)} y2={y(t)} className={t === 0 ? "axis" : "grid"} />
            <text x={PAD.l - 6} y={y(t) + 4} className="tick" textAnchor="end">{fmt(t)}</text>
          </g>
        ))}
        {data.map((r, i) => i % labelEvery === 0 && (
          <text key={i} x={x(i)} y={height - 8} className="tick" textAnchor="middle">{xFmt(String(r[xKey]))}</text>
        ))}
        <path d={wash} fill={color} opacity={0.1} />
        <path d={path} fill="none" stroke={color} strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />
        {hover != null && <line x1={x(hover)} x2={x(hover)} y1={PAD.t} y2={PAD.t + ih} className="crosshair" />}
        {valid.map((p) => (
          <circle key={p.i} cx={x(p.i)} cy={y(p.v)} r={hover === p.i ? 5 : 4} fill={color} className="dot" />
        ))}
      </svg>
      {hover != null && (
        <Tooltip x={x(hover)} y={y(pts[hover].v ?? 0)} w={w}>
          <b>{xFmt(String(data[hover][xKey]))}</b>
          <div className="tip-row"><i style={{ background: color }} />{pts[hover].v == null ? "nincs értékelés" : fmt(pts[hover].v!)}</div>
          {extra?.(data[hover])}
        </Tooltip>
      )}
    </div>
  );
}

// ------------------------------------------------------------------ vízszintes sáv (rangsor)

export function HBarChart({ data, labelKey, valueKey, color, fmt = (v) => String(v), extra }: {
  data: Row[]; labelKey: string; valueKey: string; color: string; fmt?: (v: number) => string; extra?: (r: Row) => ReactNode;
}) {
  const [hover, setHover] = useState<number | null>(null);
  if (!data.length) return <div className="chart-empty">Nincs adat a kiválasztott időszakban.</div>;
  const max = Math.max(...data.map((r) => num(r, valueKey)), 1);
  return (
    <div className="hbars" onMouseLeave={() => setHover(null)}>
      {data.map((r, i) => (
        <div key={i} className={`hbar${hover === i ? " on" : ""}`} onMouseEnter={() => setHover(i)}>
          <span className="hbar-label" title={String(r[labelKey])}>{String(r[labelKey])}</span>
          <span className="hbar-track">
            <span className="hbar-fill" style={{ width: `${(num(r, valueKey) / max) * 100}%`, background: color }} />
            <span className="hbar-val">{fmt(num(r, valueKey))}</span>
          </span>
          {hover === i && extra && <div className="chart-tip inline">{extra(r)}</div>}
        </div>
      ))}
    </div>
  );
}
