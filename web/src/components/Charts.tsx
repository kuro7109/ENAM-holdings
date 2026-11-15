/* Small SVG charts, one axis each, thin marks, a readout line that answers "what's this mark?"
   on hover or tap (mobile has no hover), and text in text tokens, never the series colour. */
import { useState } from "react";

const W = 340;
const SERIES = "var(--blue)";        // the series the story is about
const COMPARE = "#7b8494";           // the reference series (3.5:1 on sheets)

type Fmt = (v: number | null) => string;

/** Path for a bar with a 4px rounded data-end and a square baseline end. */
function barPath(x: number, base: number, end: number, w: number): string {
  const r = Math.min(4, w / 2, Math.abs(end - base));
  if (end <= base) { // grows upward
    return `M${x},${base}V${end + r}Q${x},${end} ${x + r},${end}H${x + w - r}Q${x + w},${end} ${x + w},${end + r}V${base}Z`;
  }
  return `M${x},${base}V${end - r}Q${x},${end} ${x + r},${end}H${x + w - r}Q${x + w},${end} ${x + w},${end - r}V${base}Z`;
}

function Readout({ text }: { text: string }) {
  return <div className="readout" aria-live="polite">{text}</div>;
}

/** Columns over time (one series). Negative values hang below a zero line. */
export function Columns({ labels, values, fmt, height = 92, title, highlight = "last", vw = W, onPick, selected }: {
  labels: string[]; values: (number | null)[]; fmt: Fmt; height?: number; title: string;
  highlight?: "last" | "none"; vw?: number; onPick?: (i: number) => void; selected?: number | null;
}) {
  const W = vw;
  const n = values.length;
  const [active, setActive] = useState(n - 1);
  if (!n) return null;
  const nums = values.map((v) => v ?? 0);
  const max = Math.max(0, ...nums), min = Math.min(0, ...nums);
  const span = max - min || 1;
  const pad = 4, H = height;
  const y = (v: number) => pad + ((max - v) / span) * (H - pad * 2);
  const band = W / n, bw = Math.min(24, band - 2);
  return (
    <figure className="chart">
      <figcaption>{title}</figcaption>
      <Readout text={`${labels[active]}: ${fmt(values[active])}`} />
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`${title}. ${labels.map((l, i) => `${l} ${fmt(values[i])}`).join(", ")}`}>
        <line x1="0" x2={W} y1={y(0)} y2={y(0)} className="axis" />
        {values.map((v, i) => {
          const x = i * band + (band - bw) / 2;
          const on = selected != null ? i === selected || i === active : i === active || (highlight === "last" && i === n - 1);
          return (
            <g key={labels[i] + i} onPointerEnter={() => setActive(i)} onClick={() => { setActive(i); onPick?.(i); }}
              style={onPick ? { cursor: "pointer" } : undefined}>
              {v != null && <path d={barPath(x, y(0), y(v), bw)} fill={v < 0 ? "var(--down)" : SERIES}
                opacity={on ? 1 : 0.55} />}
              <rect x={i * band} y="0" width={band} height={H} fill="transparent" />
            </g>
          );
        })}
      </svg>
      <div className="axis-labels"><span>{labels[0]}</span><span>{labels[n - 1]}</span></div>
    </figure>
  );
}

/** A level over time (e.g. margin %), 2px line, end dot with a surface ring. */
export function Line({ labels, values, fmt, height = 70, title }: {
  labels: string[]; values: (number | null)[]; fmt: Fmt; height?: number; title: string;
}) {
  const n = values.length;
  const [active, setActive] = useState(n - 1);
  const pts = values.map((v, i) => ({ v, i })).filter((p) => p.v != null) as { v: number; i: number }[];
  if (pts.length < 2) return null;
  const lo = Math.min(...pts.map((p) => p.v)), hi = Math.max(...pts.map((p) => p.v));
  const span = hi - lo || 1, H = height, pad = 8;
  const x = (i: number) => (n === 1 ? W / 2 : 6 + (i / (n - 1)) * (W - 12));
  const y = (v: number) => pad + ((hi - v) / span) * (H - pad * 2);
  const d = pts.map((p, k) => `${k ? "L" : "M"}${x(p.i)},${y(p.v)}`).join("");
  const a = pts.find((p) => p.i === active) || pts[pts.length - 1];
  return (
    <figure className="chart">
      <figcaption>{title}</figcaption>
      <Readout text={`${labels[a.i]}: ${fmt(a.v)}  ·  range ${fmt(lo)} to ${fmt(hi)}`} />
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`${title}. ${labels.map((l, i) => `${l} ${fmt(values[i])}`).join(", ")}`}>
        <line x1="0" x2={W} y1={H - 1} y2={H - 1} className="axis" />
        <path d={d} fill="none" stroke={SERIES} strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" />
        <circle cx={x(a.i)} cy={y(a.v)} r="4" fill={SERIES} stroke="var(--paper-2)" strokeWidth="2" />
        {values.map((_, i) => (
          <rect key={i} x={x(i) - W / n / 2} y="0" width={W / n} height={H} fill="transparent"
            onPointerEnter={() => setActive(i)} onClick={() => setActive(i)} />
        ))}
      </svg>
      <div className="axis-labels"><span>{labels[0]}</span><span>{labels[n - 1]}</span></div>
    </figure>
  );
}

/** Two series per period: the one the story is about in blue, the reference in grey. */
export function Paired({ labels, a, b, fmt, height = 100, title }: {
  labels: string[]; a: { name: string; values: (number | null)[] }; b: { name: string; values: (number | null)[] };
  fmt: Fmt; height?: number; title: string;
}) {
  const n = labels.length;
  const [active, setActive] = useState(n - 1);
  if (!n) return null;
  const all = [...a.values, ...b.values].map((v) => v ?? 0);
  const max = Math.max(0, ...all), min = Math.min(0, ...all), span = max - min || 1;
  const H = height, pad = 4;
  const y = (v: number) => pad + ((max - v) / span) * (H - pad * 2);
  const band = W / n, bw = Math.min(14, (band - 8) / 2);
  return (
    <figure className="chart">
      <figcaption>{title}</figcaption>
      <div className="legend">
        <span><b style={{ background: SERIES }} />{a.name}</span>
        <span><b style={{ background: COMPARE }} />{b.name}</span>
      </div>
      <Readout text={`${labels[active]}: ${a.name} ${fmt(a.values[active])} · ${b.name} ${fmt(b.values[active])}`} />
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`${title}. ${labels.map((l, i) => `${l}: ${a.name} ${fmt(a.values[i])}, ${b.name} ${fmt(b.values[i])}`).join("; ")}`}>
        <line x1="0" x2={W} y1={y(0)} y2={y(0)} className="axis" />
        {labels.map((l, i) => {
          const x0 = i * band + (band - (bw * 2 + 2)) / 2;
          const va = a.values[i], vb = b.values[i];
          return (
            <g key={l + i} onPointerEnter={() => setActive(i)} onClick={() => setActive(i)} opacity={i === active ? 1 : 0.7}>
              {va != null && <path d={barPath(x0, y(0), y(va), bw)} fill={va < 0 ? "var(--down)" : SERIES} />}
              {vb != null && <path d={barPath(x0 + bw + 2, y(0), y(vb), bw)} fill={COMPARE} />}
              <rect x={i * band} y="0" width={band} height={H} fill="transparent" />
            </g>
          );
        })}
      </svg>
      <div className="axis-labels"><span>{labels[0]}</span><span>{labels[n - 1]}</span></div>
    </figure>
  );
}

/** Ranked horizontal bars across companies or stocks. Diverging mode centres zero. */
export function HBars({ rows, fmt, title, diverging = false, onPick, polarity = false }: {
  rows: { key: string; label: string; value: number | null; sub?: string }[]; fmt: Fmt; title: string;
  diverging?: boolean; onPick?: (key: string) => void; polarity?: boolean;
}) {
  const vals = rows.map((r) => r.value ?? 0);
  diverging = diverging || vals.some((v) => v < 0);
  const maxAbs = Math.max(...vals.map(Math.abs), 0.0001);
  const max = Math.max(...vals, 0);
  return (
    <figure className="chart">
      <figcaption>{title}</figcaption>
      <ul className="hbars" role="list">
        {rows.map((r) => {
          const v = r.value;
          const w = v == null ? 0 : diverging ? (Math.abs(v) / maxAbs) * 50 : (Math.max(v, 0) / (max || 1)) * 100;
          const neg = v != null && v < 0;
          const inner = (
            <>
              <span className="hb-label">{r.label}{r.sub && <span className="faint"> {r.sub}</span>}</span>
              <span className={`hb-track ${diverging ? "div" : ""}`}>
                {v != null && (
                  <i style={diverging
                    ? { width: `${w}%`, [neg ? "right" : "left"]: "50%", background: neg ? "var(--down)" : polarity ? "var(--up)" : SERIES,
                      borderRadius: neg ? "4px 0 0 4px" : "0 4px 4px 0" }
                    : { width: `${w}%`, left: 0, background: SERIES, borderRadius: "0 4px 4px 0" }} />
                )}
              </span>
              <span className="hb-val num">{fmt(v)}</span>
            </>
          );
          return (
            <li key={r.key}>
              {onPick ? <button className="hb-row" onClick={() => onPick(r.key)}>{inner}</button> : <div className="hb-row">{inner}</div>}
            </li>
          );
        })}
      </ul>
    </figure>
  );
}

/** Target vs actual for one promise: the guided band, and where the number landed. */
export function Bullet({ low, high, actual, unit, verdict }: {
  low: number; high?: number | null; actual: number; unit: string; verdict: string;
}) {
  const top = Math.max(actual, high ?? low, low) * 1.2 || 1;
  const bottom = Math.min(0, actual);
  const span = top - bottom;
  const px = (v: number) => ((v - bottom) / span) * 100;
  const good = verdict === "delivered" || verdict === "on_track";
  const color = good ? "var(--up)" : verdict === "missed" ? "var(--down)" : "var(--amber)";
  const f = (v: number) => (unit.includes("cr") ? `₹${Math.round(v).toLocaleString("en-IN")} cr` : `${v.toFixed(1)}%`);
  return (
    <div className="bullet" aria-label={`Target ${f(low)}${high ? ` to ${f(high)}` : ""}, actual ${f(actual)}`}>
      <div className="bl-track">
        <span className="bl-band" style={{ left: `${px(low)}%`, width: `${Math.max(1.5, px(high ?? low) - px(low))}%` }} />
        <span className="bl-actual" style={{ left: `${px(Math.min(actual, 0))}%`, width: `${Math.abs(px(actual) - px(Math.max(0, bottom)))}%`, background: color }} />
      </div>
      <div className="bl-legend tiny">
        <span><b className="sw band" />Promised {f(low)}{high && high !== low ? `–${f(high)}` : ""}</span>
        <span><b className="sw" style={{ background: color }} />Actual {f(actual)}</span>
      </div>
    </div>
  );
}
