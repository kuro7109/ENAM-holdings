/* One company's research, laid out visual-first: a header that answers "should I trust this
   management?", then five tabs so nothing needs a long scroll. */
import { useState } from "react";
import { Bullet, Columns, Line, Paired } from "../components/Charts";
import { num, pct, rs } from "../lib";

export const VERDICTS: [string, string, string][] = [
  ["delivered", "Delivered", "var(--up)"], ["on_track", "On track", "#6aa486"], ["partly", "Partly", "var(--amber)"],
  ["behind", "Behind", "#d08a3c"], ["missed", "Missed", "var(--down)"],
  ["too_early", "Too early", "#9aa3b2"], ["unverifiable", "Can't verify", "#c4cad3"],
];
const ORDER = ["missed", "behind", "partly", "delivered", "on_track", "too_early", "unverifiable"];
const label = (k: string) => VERDICTS.find(([v]) => v === k)?.[1] || k;
const color = (k: string) => VERDICTS.find(([v]) => v === k)?.[2] || "#c4cad3";

/** Pull a plottable target/actual pair out of a code-checked promise, if it has one. */
function numericPromise(p: any): { low: number; high: number | null; actual: number; unit: string } | null {
  if (p.checked_by !== "code" || p.target_low == null || !p.actual) return null;
  const rupees = /₹/.test(p.actual);
  const m = String(p.actual).replace(/,/g, "").match(/-?\d+(\.\d+)?/);
  if (!m) return null;
  return { low: +p.target_low, high: p.target_high != null ? +p.target_high : null, actual: +m[0], unit: rupees ? "₹ cr" : "%" };
}

const kept = (t: Record<string, number>) => {
  const judged = (t.delivered || 0) + (t.on_track || 0) + (t.partly || 0) + (t.behind || 0) + (t.missed || 0);
  return judged ? Math.round((((t.delivered || 0) + (t.on_track || 0)) / judged) * 100) : null;
};

function TallyBar({ tally, total }: { tally: Record<string, number>; total: number }) {
  return (
    <>
      <div className="tally tall" role="img" aria-label={VERDICTS.map(([k, l]) => `${tally[k] || 0} ${l}`).join(", ")}>
        {VERDICTS.map(([k, , c]) => tally[k] ? <i key={k} style={{ width: `${(tally[k] / total) * 100}%`, background: c }} /> : null)}
      </div>
      <div className="legend">
        {VERDICTS.filter(([k]) => tally[k]).map(([k, l, c]) => <span key={k}><b style={{ background: c }} />{tally[k]} {l.toLowerCase()}</span>)}
      </div>
    </>
  );
}

function Spark({ values, w = 120, h = 30 }: { values: (number | null)[]; w?: number; h?: number }) {
  const v = values.map((x, i) => ({ x: i, y: x })).filter((p) => p.y != null) as { x: number; y: number }[];
  if (v.length < 2) return null;
  const lo = Math.min(...v.map((p) => p.y)), hi = Math.max(...v.map((p) => p.y)), span = hi - lo || 1;
  const n = values.length - 1 || 1;
  const X = (i: number) => 3 + (i / n) * (w - 6), Y = (y: number) => 4 + ((hi - y) / span) * (h - 8);
  const last = v[v.length - 1];
  return (
    <svg className="tile-spark" viewBox={`0 0 ${w} ${h}`} aria-hidden="true">
      <path d={v.map((p, k) => `${k ? "L" : "M"}${X(p.x)},${Y(p.y)}`).join("")} fill="none" stroke="var(--blue)" strokeWidth="1.6" strokeLinejoin="round" />
      <circle cx={X(last.x)} cy={Y(last.y)} r="3" fill="var(--blue)" stroke="var(--paper-2)" strokeWidth="1.5" />
    </svg>
  );
}

function Tile({ label: l, value, tone, trend, hint, onClick }: {
  label: string; value: string; tone?: "up" | "down" | ""; trend?: (number | null)[]; hint?: string; onClick?: () => void;
}) {
  const Tag = onClick ? "button" : "div";
  return (
    <Tag className="tile" onClick={onClick} title={hint}>
      <span className="tile-label">{l}</span>
      <span className={`tile-value num ${tone || ""}`}>{value}</span>
      {trend && <Spark values={trend} />}
    </Tag>
  );
}

const TABS = [["overview", "Overview"], ["promises", "Promises"], ["financials", "Numbers"], ["case", "Bull & bear"]] as const;
type TabKey = (typeof TABS)[number][0];

export function Research({ r }: { r: any }) {
  const [tab, setTab] = useState<TabKey>("overview");
  const go = (t: TabKey) => { setTab(t); document.querySelector(".r-tabs")?.scrollIntoView({ block: "start", behavior: "smooth" }); };
  const total = r.promises?.length || 0;
  const k = kept(r.tally || {});
  return (
    <article className="research">
      <header className="r-head">
        <div className="need-head">
          <span className="sym" style={{ fontSize: 24 }}>{r.symbol}</span>
          <span className="cat">as of {r.as_of}</span>
        </div>
        <div className="muted small">{r.name}</div>
        {r.verdict && <p className="verdict">{r.verdict}</p>}
        {total > 0 && (
          <button className="score" onClick={() => go("promises")}>
            <span className="score-num num">{k != null ? `${k}%` : "–"}</span>
            <span className="score-text">
              of judged promises kept
              <span className="faint tiny"> · {total} promises from {r.calls?.filter((c: any) => c.status === "ok").length} earnings calls</span>
            </span>
          </button>
        )}
        {total > 0 && <TallyBar tally={r.tally} total={total} />}
      </header>

      <nav className="r-tabs" role="tablist" aria-label="Research sections">
        {TABS.map(([key, l]) => (
          <button key={key} role="tab" aria-selected={tab === key} className="r-tab" onClick={() => setTab(key)}>{l}</button>
        ))}
      </nav>

      <div className="r-panel" role="tabpanel">
        {tab === "overview" && <Overview r={r} go={go} />}
        {tab === "promises" && <Promises r={r} />}
        {tab === "financials" && <Financials r={r} />}
        {tab === "case" && <Case r={r} />}
      </div>
    </article>
  );
}

function Overview({ r, go }: { r: any; go: (t: TabKey) => void }) {
  const s = r.snapshot || {}, tr = r.trajectory || {}, bal = r.balance || {}, cash = r.cash || {};
  const q = (tr.quarterly || []).slice(-12), a = tr.annual || [];
  const roce = bal.working_capital?.["ROCE %"]?.map((x: any) => x.value);
  const tone = (v: number | null | undefined, goodUp = true) => (v == null ? "" : (v > 0) === goodUp ? "up" : "down");
  const watch = [...(r.promises || [])].filter((p: any) => ["missed", "behind", "partly"].includes(p.verdict))
    .sort((x: any, y: any) => ORDER.indexOf(x.verdict) - ORDER.indexOf(y.verdict)).slice(0, 3);
  const seg = (r.business?.ar_segments?.length ? r.business.ar_segments : r.business?.segments) || [];
  const segPct = seg.map((g: any) => ({ name: g.name, p: parseFloat(String(g.revenue_share || g.share_or_growth || "").match(/(\d+(\.\d+)?)\s*%/)?.[1] || "") }))
    .filter((g: any) => !Number.isNaN(g.p) && g.p > 0 && g.p <= 100);
  return (
    <>
      <div className="section-title">Key numbers <span className="faint">tap for charts</span></div>
      <div className="tiles">
        <Tile label="Sales, last 12 months" value={rs(s.ttm_sales)} trend={q.map((x: any) => x.sales)} onClick={() => go("financials")} />
        <Tile label={`${s.last_q || "Latest"} sales growth`} value={pct(s.last_q_sales_yoy)} tone={tone(s.last_q_sales_yoy)} trend={q.map((x: any) => x.sales_yoy ?? null)} onClick={() => go("financials")} />
        <Tile label={`${s.last_q || "Latest"} EBITDA margin`} value={pct(s.last_q_opm, 0, false)} trend={q.map((x: any) => x.opm)} onClick={() => go("financials")} />
        <Tile label={`${s.last_q || "Latest"} profit growth`} value={pct(s.last_q_pat_yoy)} tone={tone(s.last_q_pat_yoy)} trend={q.map((x: any) => x.pat_yoy ?? null)} onClick={() => go("financials")} />
        <Tile label="Return on capital" value={pct(s.roce, 0, false)} trend={roce} onClick={() => go("financials")} />
        <Tile label="Cash conversion, 3 yrs" value={cash.cfo_to_pat_3y != null ? `${cash.cfo_to_pat_3y}×` : "–"}
          tone={cash.cfo_to_pat_3y == null ? "" : cash.cfo_to_pat_3y >= 0.9 ? "up" : "down"} trend={(cash.years || []).map((y: any) => y.cfo)}
          hint="Operating cash flow divided by net profit. Near or above 1× means profits turn into cash." onClick={() => go("financials")} />
        <Tile label="Debt to equity" value={bal.de != null ? `${bal.de}×` : "–"} trend={a.map((y: any) => y.de ?? null)} onClick={() => go("financials")} />
        <Tile label="Price to earnings" value={s.pe != null ? `${num(s.pe, 1)}×` : "–"} hint="Share price divided by earnings per share." />
      </div>

      {r.narrative_vs_numbers?.length > 0 && (
        <>
          <div className="section-title">What they say vs what the numbers say</div>
          <ul className="nvn">
            {r.narrative_vs_numbers.map((n: any, i: number) => (
              <li key={i} className={n.agree ? "ok" : "bad"}>
                <span className="nvn-mark" aria-label={n.agree ? "agrees" : "diverges"}>{n.agree ? "✓" : "✕"}</span>
                <span><span className="nvn-claim">{n.claim}</span><span className="nvn-real">{n.reality}</span></span>
              </li>
            ))}
          </ul>
        </>
      )}

      {watch.length > 0 && (
        <>
          <div className="section-title">What to watch <button className="linkbtn" onClick={() => go("promises")}>All promises</button></div>
          {watch.map((p: any) => <PromiseCard key={p.id} p={p} compact />)}
        </>
      )}

      {(r.business?.what_it_does || r.business?.about) && (
        <>
          <div className="section-title">The business</div>
          <p className="small clamp3" style={{ marginTop: 4 }}>{r.business.what_it_does || r.business.about}</p>
          {segPct.length > 1 && (
            <div className="segbar" role="img" aria-label={segPct.map((g: any) => `${g.name} ${g.p}%`).join(", ")}>
              {segPct.map((g: any, i: number) => <i key={g.name} style={{ width: `${g.p}%`, opacity: 1 - i * 0.22 }} title={`${g.name} ${g.p}%`} />)}
            </div>
          )}
          <div className="cats">{seg.slice(0, 6).map((g: any) => <span key={g.name} className="pill">{g.name}<span className="faint"> {g.revenue_share || g.share_or_growth}</span></span>)}</div>
        </>
      )}

      <div className="section-title">Sources</div>
      <Sources r={r} />
    </>
  );
}

function PromiseCard({ p, compact = false }: { p: any; compact?: boolean }) {
  const [open, setOpen] = useState(false);
  const np = numericPromise(p);
  const link = p.call_url ? `${p.call_url}${p.page ? `#page=${p.page}` : ""}` : null;
  return (
    <div className={`pcard ${compact ? "compact" : ""}`} style={{ borderLeftColor: color(p.verdict) }}>
      <div className="pcard-head">
        <span className="vbadge" style={{ background: color(p.verdict) }}>{label(p.verdict)}</span>
        <span className="faint tiny">{p.call} call · for {p.horizon || "unspecified"}</span>
      </div>
      <button className={`pquote ${open ? "open" : ""}`} onClick={() => setOpen(!open)} aria-expanded={open}>“{p.quote}”</button>
      {np ? <Bullet {...np} verdict={p.verdict} /> : p.actual && <div className="small">Actual: <b style={{ fontWeight: 600 }}>{p.actual}</b></div>}
      {open && (
        <div className="tiny faint" style={{ marginTop: 6 }}>
          {p.note && <div className="muted small" style={{ marginBottom: 4 }}>{p.note}</div>}
          {p.speaker && <>{p.speaker} · </>}
          {p.checked_by === "code" ? "Checked against reported numbers" : "Judged from the numbers and later calls"}
          {link && <> · <a href={link} target="_blank" rel="noreferrer">Transcript p.{p.page}</a></>}
        </div>
      )}
    </div>
  );
}

function Promises({ r }: { r: any }) {
  const [filter, setFilter] = useState("all");
  const [shown, setShown] = useState(8);
  const all = [...(r.promises || [])].sort((x: any, y: any) => ORDER.indexOf(x.verdict) - ORDER.indexOf(y.verdict));
  if (!all.length) {
    return <p className="small muted">{!r.calls?.length
      ? "No earnings-call transcripts are listed for this company, so there are no management promises to track."
      : "Promise tracking hasn't run for this company yet."} The Financials tab is complete.</p>;
  }
  const list = filter === "all" ? all : all.filter((p: any) => p.verdict === filter);
  const byCall: Record<string, Record<string, number>> = {};
  for (const p of all) (byCall[p.call] ||= {})[p.verdict] = ((byCall[p.call] || {})[p.verdict] || 0) + 1;
  const calls = (r.calls || []).map((c: any) => c.quarter).filter((c: string) => byCall[c]).reverse();
  return (
    <>
      <div className="section-title">Verdicts by earnings call</div>
      <div className="bycall">
        {calls.map((c: string) => {
          const t = byCall[c], n = Object.values(t).reduce((a, b) => a + b, 0);
          return (
            <div key={c} className="bycall-row">
              <span className="small">{c}</span>
              <div className="tally" role="img" aria-label={`${c}: ${Object.entries(t).map(([k, v]) => `${v} ${label(k)}`).join(", ")}`}>
                {VERDICTS.map(([k, , col]) => t[k] ? <i key={k} style={{ width: `${(t[k] / n) * 100}%`, background: col }} /> : null)}
              </div>
              <span className="num small">{n}</span>
            </div>
          );
        })}
      </div>
      <div className="cats" role="group" aria-label="Filter promises" style={{ marginTop: 14 }}>
        <button className="chip sm" aria-pressed={filter === "all"} onClick={() => { setFilter("all"); setShown(8); }}>All {all.length}</button>
        {VERDICTS.filter(([k]) => r.tally?.[k]).map(([k, l, c]) => (
          <button key={k} className="chip sm" aria-pressed={filter === k} onClick={() => { setFilter(k); setShown(8); }}>
            <b className="dot-sw" style={{ background: c }} />{l} {r.tally[k]}
          </button>
        ))}
      </div>
      {list.slice(0, shown).map((p: any) => <PromiseCard key={p.id} p={p} />)}
      {list.length > shown && (
        <button className="fold" onClick={() => setShown(shown + 8)}>
          <span><b>{list.length - shown} more.</b> Tap a quote to see who said it and the transcript page.</span>
          <span className="linkbtn">Show 8 more</span>
        </button>
      )}
    </>
  );
}

function Financials({ r }: { r: any }) {
  const tr = r.trajectory || {}, bal = r.balance || {}, cash = r.cash || {};
  const q = (tr.quarterly || []).slice(-12), a = (tr.annual || []).slice(-8);
  const years = (cash.years || []).filter((y: any) => y.cfo != null || y.pat != null);
  const dd = bal.working_capital?.["Debtor Days"] || bal.working_capital?.["Cash Conversion Cycle"];
  const ql = q.map((x: any) => x.q || x.period), al = a.map((x: any) => x.fy);
  return (
    <>
      <div className="tiles four">
        <Tile label="Sales CAGR, 3 yrs" value={pct(tr.sales_cagr_3y)} />
        <Tile label="Sales CAGR, 5 yrs" value={pct(tr.sales_cagr_5y)} />
        <Tile label="Profit CAGR, 3 yrs" value={pct(tr.pat_cagr_3y)} />
        <Tile label="Margin change, 3 yrs" value={tr.opm_change_3y != null ? `${tr.opm_change_3y > 0 ? "+" : ""}${tr.opm_change_3y} pts` : "–"} />
      </div>
      <div className="section-title">Growth</div>
      <div className="charts-2">
        <Columns title="Quarterly sales, ₹ cr" labels={ql} values={q.map((x: any) => x.sales)} fmt={rs} />
        <Line title="EBITDA margin, %" labels={ql} values={q.map((x: any) => x.opm)} fmt={(v) => (v == null ? "–" : `${v.toFixed(0)}%`)} />
        <Columns title="Annual sales, ₹ cr" labels={al} values={a.map((x: any) => x.sales)} fmt={rs} />
        <Columns title="Annual net profit, ₹ cr" labels={al} values={a.map((x: any) => x.pat)} fmt={rs} />
      </div>
      <div className="section-title">Quality of earnings</div>
      <div className="charts-2">
        {years.length > 1 && (
          <Paired title="Is profit turning into cash? ₹ cr" labels={years.map((y: any) => y.fy)}
            a={{ name: "Operating cash flow", values: years.map((y: any) => y.cfo) }}
            b={{ name: "Net profit", values: years.map((y: any) => y.pat) }} fmt={rs} />
        )}
        {dd && dd.length > 2 && (
          <Line title={Object.keys(bal.working_capital).includes("Debtor Days") ? "Debtor days (lower is better)" : "Cash conversion cycle, days"}
            labels={dd.map((x: any) => x.period)} values={dd.map((x: any) => x.value)} fmt={(v) => (v == null ? "–" : `${Math.round(v)} days`)} />
        )}
        {a.some((x: any) => x.de != null) && (
          <Line title="Debt to equity, ×" labels={al} values={a.map((x: any) => x.de ?? null)} fmt={(v) => (v == null ? "–" : `${v.toFixed(2)}×`)} />
        )}
        {bal.working_capital?.["ROCE %"] && (
          <Line title="Return on capital, %" labels={bal.working_capital["ROCE %"].map((x: any) => x.period)}
            values={bal.working_capital["ROCE %"].map((x: any) => x.value)} fmt={(v) => (v == null ? "–" : `${v.toFixed(0)}%`)} />
        )}
      </div>
    </>
  );
}

function Case({ r }: { r: any }) {
  const tones = (r.calls || []).filter((c: any) => c.tone);
  const push = [...new Set((r.calls || []).flatMap((c: any) => c.pushback || []))].slice(0, 6) as string[];
  return (
    <>
      <div className="case2">
        <section className="panel bull">
          <h3>▲ Bull case</h3>
          <ul>{(r.bull || []).map((b: any, i: number) => <li key={i}>{b.point}{b.cite && <span className="cite-chip">{b.cite}</span>}</li>)}</ul>
        </section>
        <section className="panel bear">
          <h3>▼ Bear case</h3>
          <ul>{(r.bear || []).map((b: any, i: number) => <li key={i}>{b.point}{b.cite && <span className="cite-chip">{b.cite}</span>}</li>)}</ul>
        </section>
      </div>
      {push.length > 0 && (
        <>
          <div className="section-title">What analysts pushed on</div>
          <div className="cats">{push.map((x) => <span key={x} className="pill">{x}</span>)}</div>
        </>
      )}
      {tones.length > 0 && (
        <>
          <div className="section-title">Management's tone, call by call</div>
          <ol className="timeline">
            {tones.map((c: any) => <li key={c.quarter}><span className="tl-q">{c.quarter}</span><span className="small">{c.tone}</span></li>)}
          </ol>
        </>
      )}
    </>
  );
}

function Sources({ r }: { r: any }) {
  const icon: Record<string, string> = { financials: "▦", transcript: "❝", annual_report: "▤" };
  return (
    <>
      <ul className="srcs">
        {(r.sources || []).map((x: any) => (
          <li key={x.url + x.label}><span className="src-ic" aria-hidden="true">{icon[x.type] || "•"}</span>
            <a href={x.url} target="_blank" rel="noreferrer">{x.label}</a></li>
        ))}
      </ul>
      <div className="tiles three" style={{ marginTop: 14 }}>
        <Tile label="Model calls" value={String(r.cost?.calls ?? 0)} />
        <Tile label="Tokens read" value={num(r.cost?.tokens_in)} />
        <Tile label="Seconds" value={String(r.cost?.seconds ?? "–")} />
      </div>
      <p className="faint tiny">{r.discipline}</p>
    </>
  );
}
