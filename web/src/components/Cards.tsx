import { useState } from "react";
import type { FeedItem, Person, Results } from "../lib";
import { Columns } from "./Charts";
import { CATEGORY_LABEL, num, pct, times, tone, when } from "../lib";

export function Spark({ values, w = 74, h = 26 }: { values: (number | null)[]; w?: number; h?: number }) {
  const v = values.filter((x): x is number => x != null);
  if (v.length < 2) return <svg width={w} height={h} />;
  const lo = Math.min(...v), hi = Math.max(...v), span = hi - lo || 1;
  const pts = v.map((x, i) => `${(i / (v.length - 1)) * w},${h - 2 - ((x - lo) / span) * (h - 4)}`).join(" ");
  const up = v[v.length - 1] >= v[0];
  return (
    <svg width={w} height={h} viewBox={`0 0 ${w} ${h}`} aria-hidden="true">
      <polyline points={pts} fill="none" stroke={up ? "var(--up)" : "var(--down)"} strokeWidth="1.5" strokeLinejoin="round" />
    </svg>
  );
}

export function ResultsTable({ r }: { r: Results }) {
  // Filings report in lakhs, crores or millions; show everything in ₹ crore so cards compare.
  const u = (r.unit || "").toLowerCase();
  const k = u.includes("lakh") ? 0.01 : u.includes("million") || u.includes("mn") ? 0.1 : 1;
  const unit = /lakh|million|crore|cr\b|mn/.test(u) ? "₹ cr" : (r.unit || "");
  const c = (x: number | null) => (x == null ? null : x * k);
  const em = r.margins.ebitda;
  return (
    <>
      <table className="ledger">
        <thead>
          <tr>
            <th scope="col">{r.labels.current || "This quarter"}</th>
            <th scope="col">{unit}</th>
            <th scope="col">QoQ</th>
            <th scope="col">YoY</th>
          </tr>
        </thead>
        <tbody>
          {r.rows.filter((row) => row.current != null).map((row) => (
            <tr key={row.key}>
              <td>{row.metric}</td>
              <td className="num now">{num(c(row.current))}</td>
              <td className={`num ${tone(row.qoq)}`}>{pct(row.qoq, 0)}</td>
              <td className={`num ${tone(row.yoy)}`}>{pct(row.yoy, 0)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="mini">
        {r.rows.filter((row) => row.key === "revenue" || row.key === "pat").filter((row) => row.current != null).map((row) => (
          <Columns key={row.key} title={`${row.metric}, ₹ cr`} height={56} vw={150} labels={["Year ago", "Last qtr", "This qtr"]}
            values={[c(row.year_ago_quarter), c(row.previous_quarter), c(row.current)]}
            fmt={(v) => (v == null ? "not in filing" : num(v))} />
        ))}
      </div>
      {em && em.current != null ? (
        <div className="foot">
          EBITDA margin <span className="num">{pct(em.current, 1, false)}</span>
          {em.year_ago_quarter != null && <> vs <span className="num">{pct(em.year_ago_quarter, 1, false)}</span> a year ago</>} ·{" "}
          {r.statement} · {r.ebitda_note}
        </div>
      ) : !r.is_lender && <div className="foot">{r.statement}. EBITDA not computable from this filing's table.</div>}
      {r.is_lender && <div className="foot">Lender: EBITDA isn't meaningful, so it's left out. {r.statement}.</div>}
      {r.checks.map((c) => (
        <div className="check" key={c}>Check: {c}</div>
      ))}
    </>
  );
}

const IN = new Set(["appointed", "redesignated", "reappointed"]);

export function People({ people }: { people: Person[] }) {
  return (
    <>
      {people.map((p) => {
        const incoming = IN.has(p.change);
        const bio = p.bio || p.profile;
        return (
          <div className="person" key={p.name + p.change}>
            <span className={`dir ${incoming ? "in" : "out"}`} aria-label={incoming ? "joining" : "leaving"}>
              {incoming ? "+" : "−"}
            </span>
            <div>
              <span className="who">{p.name}</span>{" "}
              <span className="muted small">
                {p.change} {p.role ? `as ${p.role}` : ""}
                {p.effective ? `, from ${p.effective}` : ""}
              </span>
            </div>
            {bio && (
              <div className="bio">
                {bio}
                {p.bio && p.bio_sources?.[0] && (
                  <>
                    {" "}
                    <a href={p.bio_sources[0]} target="_blank" rel="noreferrer">Source</a>
                  </>
                )}
                {!p.bio && p.profile && <span className="faint"> (from the filing)</span>}
              </div>
            )}
            {p.reason && <div className="bio">Reason given: {p.reason}</div>}
          </div>
        );
      })}
    </>
  );
}

export function NeedItem({ item, onDone, leaving }: { item: FeedItem; onDone: () => void; leaving: boolean }) {
  const flagged = item.tags.includes("red_flag");
  const title = item.results ? item.results.headline || item.title : item.summary || item.title;
  return (
    <article className={`need ${flagged ? "flag" : ""} ${leaving ? "leaving" : ""}`}>
      <div className="need-head">
        <span className="sym">{item.symbol}</span>
        <span className="cat">{CATEGORY_LABEL[item.category] || item.category} · {when(item.filed_at)}</span>
      </div>
      <h2>{title}</h2>
      {item.results && <ResultsTable r={item.results} />}
      {item.management && <People people={item.management.people} />}
      {(item.why.length > 0 || item.alert) && (
        <div className="why">
          {item.why.filter((w) => !w.startsWith("PAT") && !w.startsWith("Stock moved")).map((w) => (
            <span key={w} className={w === "Red flag" ? "flag" : ""}>{w}</span>
          ))}
          {item.alert && (
            <span>
              Stock {pct(item.alert.pct_change)} on {new Date(item.alert.date).toLocaleDateString("en-IN", { day: "numeric", month: "short" })}
              {item.alert.vol_ratio && item.alert.vol_ratio >= 1.5 ? `, ${times(item.alert.vol_ratio)} volume` : ""}
            </span>
          )}
        </div>
      )}
      <div className="actions">
        <span>
          {item.pdf_url && <a href={item.pdf_url} target="_blank" rel="noreferrer">Open filing</a>}
          {item.related.length > 0 && <span className="faint small"> · +{item.related.length} related</span>}
        </span>
        <button className="done" onClick={onDone}>Done</button>
      </div>
    </article>
  );
}

export function MoveItem({ symbol, name, pctChange, vol, sigma, onDone, leaving }: {
  symbol: string; name: string; pctChange: number | null; vol: number | null; sigma: number | null;
  onDone: () => void; leaving: boolean;
}) {
  const bits = [pctChange != null ? `${pct(pctChange)} on the day` : null,
    vol != null && vol >= 1.5 ? `${times(vol)} usual volume` : null,
    sigma != null && Math.abs(sigma) >= 2 ? `a ${Math.abs(sigma).toFixed(1)}σ move for this stock` : null].filter(Boolean);
  return (
    <article className={`need move ${leaving ? "leaving" : ""}`}>
      <div className="need-head">
        <span className="sym">{symbol}</span>
        <span className="cat">Price and volume · last close</span>
      </div>
      <h2>{bits.join(", ")}</h2>
      <p className="muted small" style={{ margin: 0 }}>
        {name}. No filing explains it yet, so it may be market-wide, sector news, or something not disclosed.
      </p>
      <div className="actions">
        <span className="faint small">Thresholds are yours to set in Alerts</span>
        <button className="done" onClick={onDone}>Done</button>
      </div>
    </article>
  );
}

export function Row({ item }: { item: FeedItem }) {
  const [open, setOpen] = useState(false);
  return (
    <li className="row">
      <button className="row-btn" onClick={() => setOpen(!open)} aria-expanded={open}>
        <span><span className="sym">{item.symbol}</span> <span className="cat">{CATEGORY_LABEL[item.category] || item.category}</span></span>
        <span className="cat">{when(item.filed_at)}</span>
        <span className="line">{item.summary || item.title}</span>
      </button>
      {open && (
        <div className="more">
          {item.summary && item.title !== item.summary && <div>Filed as: {item.title}</div>}
          {item.alert && <div>Stock {pct(item.alert.pct_change)} on {item.alert.date}</div>}
          {item.pdf_url && <a href={item.pdf_url} target="_blank" rel="noreferrer">Open filing</a>}
        </div>
      )}
    </li>
  );
}
