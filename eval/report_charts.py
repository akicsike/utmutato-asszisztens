"""SVG-diagramok a mérési riporthoz (eval/report.py): oszlop, halmozott oszlop, vonal, vízszintes sáv – hover-tooltippel
(data-tip) és magyarázó felirattal. A színek a riport-sablon CSS-változói (var(--s1) …)."""

from __future__ import annotations

import html

W, H, L, R, T, B = 560, 230, 44, 14, 16, 30


def _q(s: str) -> str:
    return html.escape(s, quote=True)


def _nice(v: float) -> float:
    import math
    if v <= 0:
        return 1
    p = 10 ** math.floor(math.log10(v))
    n = v / p
    return (1 if n <= 1 else 2 if n <= 2 else 2.5 if n <= 2.5 else 5 if n <= 5 else 10) * p


def _fmt(v: float, unit: str = "") -> str:
    if unit == "%":
        return f"{round(v * 100)} %"
    if unit == "s":
        return f"{v:g} s".replace(".", ",")
    if unit == "$":
        return f"${v:.2f}"
    return f"{v:g}".replace(".", ",")


def _axes(ymax: float, unit: str, ticks: int = 4) -> list[str]:
    out = ['<g class="grid">']
    for i in range(ticks + 1):
        v = ymax * i / ticks
        y = H - B - (H - T - B) * i / ticks
        out.append(f'<line x1="{L}" x2="{W - R}" y1="{y:.1f}" y2="{y:.1f}"/>')
        out.append(f'<text x="{L - 6}" y="{y + 4:.1f}" text-anchor="end">{_q(_fmt(v, unit))}</text>')
    out.append("</g>")
    return out


def _anno(x: float, y: float, text: str, dx: float = 40, dy: float = -26) -> str:
    tx, ty = x + dx, y + dy
    anchor = "start" if dx >= 0 else "end"
    return (f'<path class="anno-line" d="M{x:.1f},{y:.1f} L{tx:.1f},{ty + 4:.1f}"/>'
            f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3" fill="var(--text-2)"/>'
            f'<text class="anno" x="{tx + (4 if dx >= 0 else -4):.1f}" y="{ty:.1f}" text-anchor="{anchor}">{_q(text)}</text>')


def chart(spec: dict) -> str:
    kind, labels, unit = spec["type"], spec["labels"], spec.get("unit", "")
    n = len(labels)
    iw, ih = W - L - R, H - T - B
    band = iw / n
    parts: list[str] = []
    legend = ""
    if kind in ("stack", "hist"):
        series = spec["series"] if kind == "stack" else [{"name": spec.get("name", "Érték"), "color": spec.get("color", "var(--s1)"), "values": spec["values"]}]
        totals = [sum(s["values"][i] for s in series) for i in range(n)]
        ymax = spec.get("ymax") or _nice(max(totals))
        parts += _axes(ymax, unit)
        bw = min(24, band * 0.6)
        for i, lab in enumerate(labels):
            cx = L + band * i + band / 2
            acc = 0.0
            nonzero = [s for s in series if s["values"][i] > 0]
            tip = f"<b>{_q(lab)}</b><br>" + "<br>".join(f"{_q(s['name'])}: {_q(_fmt(s['values'][i], unit))}" for s in series)
            for j, s in enumerate(nonzero):
                v = s["values"][i]
                y0, y1 = H - B - acc / ymax * ih, H - B - (acc + v) / ymax * ih
                acc += v
                h = max(0.0, y0 - y1 - (2 if j > 0 else 0))   # 2 px felületrés a szeletek között
                x, r = cx - bw / 2, (min(4.0, h) if j == len(nonzero) - 1 else 0.0)  # csak a legfelső szelet teteje kerek
                d = (f"M{x:.1f},{y1 + h:.1f} V{y1 + r:.1f} Q{x:.1f},{y1:.1f} {x + r:.1f},{y1:.1f} H{x + bw - r:.1f} "
                     f"Q{x + bw:.1f},{y1:.1f} {x + bw:.1f},{y1 + r:.1f} V{y1 + h:.1f} Z")
                parts.append(f'<path d="{d}" fill="{s["color"]}" data-tip="{_q(tip)}"/>')
            parts.append(f'<text x="{cx:.1f}" y="{H - 10}" text-anchor="middle">{_q(lab)}</text>')
        if "ref" in spec:
            x = L + band * spec["ref"]["at"]
            parts.append(f'<line x1="{x:.1f}" x2="{x:.1f}" y1="{T}" y2="{H - B}" stroke="var(--text-2)" stroke-dasharray="4 3"/>'
                         f'<text class="anno" x="{x + 5:.1f}" y="{T + 10}">{_q(spec["ref"]["label"])}</text>')
        if len(series) > 1:
            legend = '<div class="legend">' + "".join(f'<span><i style="background:{s["color"]}"></i>{_q(s["name"])}</span>' for s in series) + "</div>"
        for a in spec.get("anno", []):
            i = a["at"]
            cx = L + band * i + band / 2
            y = H - B - totals[i] / ymax * ih
            parts.append(_anno(cx, y - 4, a["text"], a.get("dx", 40), a.get("dy", -22)))
    elif kind == "line":
        vals = spec["values"]
        ymax = spec.get("ymax", 1)
        parts += _axes(ymax, unit)
        xs = [L + (iw * i / (n - 1) if n > 1 else iw / 2) for i in range(n)]
        pts = [(xs[i], H - B - v / ymax * ih) for i, v in enumerate(vals)]
        d = " ".join(f"{'M' if i == 0 else 'L'}{x:.1f},{y:.1f}" for i, (x, y) in enumerate(pts))
        parts.append(f'<path d="{d} L{pts[-1][0]:.1f},{H - B} L{pts[0][0]:.1f},{H - B} Z" fill="{spec.get("color", "var(--s1)")}" opacity=".1"/>')
        parts.append(f'<path d="{d}" fill="none" stroke="{spec.get("color", "var(--s1)")}" stroke-width="2" stroke-linejoin="round"/>')
        for i, (x, y) in enumerate(pts):
            tip = f"<b>{_q(labels[i])}</b><br>{_q(_fmt(vals[i], unit))}" + (f"<br>{_q(spec['tips'][i])}" if spec.get("tips") else "")
            parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="5" fill="{spec.get("color", "var(--s1)")}" stroke="var(--panel)" stroke-width="2" data-tip="{_q(tip)}"/>')
            parts.append(f'<text x="{x:.1f}" y="{H - 10}" text-anchor="middle">{_q(labels[i])}</text>')
        for a in spec.get("anno", []):
            x, y = pts[a["at"]]
            parts.append(_anno(x, y, a["text"], a.get("dx", 40), a.get("dy", -22)))
    elif kind == "hbar":
        vals = spec["values"]
        ymax = max(vals)
        rows = []
        for i, lab in enumerate(labels):
            w = vals[i] / ymax * 100
            tip = f"<b>{_q(lab)}</b><br>{_q(spec.get('name', 'Érték'))}: {_q(_fmt(vals[i], unit))}" + (f"<br>{_q(spec['tips'][i])}" if spec.get("tips") else "")
            rows.append(f'<div style="display:grid;grid-template-columns:minmax(110px,40%) 1fr;gap:8px;align-items:center;font-size:12.5px;margin:5px 0">'
                        f'<span style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:var(--text-2)">{_q(lab)}</span>'
                        f'<span style="display:flex;align-items:center;gap:6px"><span data-tip="{_q(tip)}" style="height:14px;width:{w:.1f}%;background:{spec.get("color", "var(--s1)")};border-radius:0 4px 4px 0;display:block"></span>'
                        f'<span style="font-variant-numeric:tabular-nums;color:var(--text-2)">{_q(_fmt(vals[i], unit))}</span></span></div>')
        body = "".join(rows)
        return (f'<div class="chart-demo"><h4>{_q(spec["title"])}</h4><div class="cap">{spec.get("cap", "")}</div>{body}</div>')
    svg = f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="{_q(spec["title"])}">' + "".join(parts) + "</svg>"
    return f'<div class="chart-demo"><h4>{_q(spec["title"])}</h4><div class="cap">{spec.get("cap", "")}</div>{legend}{svg}</div>'
