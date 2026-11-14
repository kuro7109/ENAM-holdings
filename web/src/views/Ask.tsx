import { useEffect, useRef, useState } from "react";
import type { Data } from "../lib";
import { num, pct } from "../lib";

const API = (import.meta.env.VITE_API_URL as string | undefined)?.replace(/\/$/, "");
type State = { status: "idle" } | { status: "running"; stage: string; symbol: string } | { status: "ready"; data: any }
  | { status: "error"; error: string };

export function Ask({ data, symbol, setSymbol }: { data: Data; symbol: string | null; setSymbol: (s: string | null) => void }) {
  const [q, setQ] = useState(symbol || "");
  const [state, setState] = useState<State>({ status: "idle" });
  const run = useRef(0);

  useEffect(() => {
    if (!symbol) return;
    setQ(symbol);
    const id = ++run.current;
    (async () => {
      setState({ status: "running", stage: "Looking for saved research", symbol });
      try {
        const r = await fetch(`/data/research/${symbol}.json`, { cache: "no-cache" });
        if (r.ok && r.headers.get("content-type")?.includes("json")) {
          if (id === run.current) setState({ status: "ready", data: await r.json() });
          return;
        }
      } catch { /* fall through to the live API */ }
      if (!API) {
        setState({ status: "error", error: `No saved research for ${symbol}, and the live research service isn't connected to this build. Run python run_research.py ${symbol} and push, or set VITE_API_URL.` });
        return;
      }
      const started = Date.now();
      while (id === run.current && Date.now() - started < 240_000) {
        try {
          const r = await fetch(`${API}/api/research/${symbol}`);
          const j = await r.json();
          if (id !== run.current) return;
          if (!r.ok) { setState({ status: "error", error: j.detail || `Service returned ${r.status}` }); return; }
          if (j.status === "ready") { setState({ status: "ready", data: j.data }); return; }
          if (j.status === "error") { setState({ status: "error", error: j.error }); return; }
          setState({ status: "running", stage: j.stage || "Working", symbol });
        } catch {
          setState({ status: "running", stage: "Waking the research service (first request can take ~50 s)", symbol });
        }
        await new Promise((res) => setTimeout(res, 2000));
      }
      if (id === run.current) setState({ status: "error", error: "Research took longer than 4 minutes. Try again; finished steps are cached." });
    })();
  }, [symbol]);

  const saved = Object.entries(data.researchIndex);
  const holdings = (data.market?.stocks || []).map((s) => s.symbol).filter((s) => !data.researchIndex[s]).slice(0, 4);
  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    const s = q.trim().toUpperCase().replace(/\.NS$|\.BO$/, "");
    if (s) setSymbol(s);
  };

  return (
    <div className="screen">
      <form className="ask" onSubmit={submit} role="search">
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Any NSE symbol, e.g. HAVELLS" aria-label="NSE symbol"
          autoCapitalize="characters" autoCorrect="off" spellCheck={false} />
        <button className="btn" type="submit">Research</button>
      </form>
      <p className="faint tiny" style={{ marginTop: 0 }}>
        Built only from the company's own filings, earnings-call transcripts and annual report. No news, no broker notes.
      </p>

      {state.status === "idle" && (
        <>
          {saved.length > 0 && (
            <>
              <div className="section-title">Ready now</div>
              <div className="cats">{saved.map(([s, v]) => <button key={s} className="chip" onClick={() => setSymbol(s)}>{s} <span className="faint">· {v.name}</span></button>)}</div>
            </>
          )}
          {holdings.length > 0 && API && (
            <>
              <div className="section-title">From your holdings <span className="faint">about a minute each</span></div>
              <div className="cats">{holdings.map((s) => <button key={s} className="chip" onClick={() => setSymbol(s)}>{s}</button>)}</div>
            </>
          )}
        </>
      )}
      {state.status === "running" && (
        <div className="progress" aria-live="polite">
          <div className="stage"><span className="pulse" />{state.stage}</div>
          <p className="muted small">Reading primary documents for {state.symbol}. Numbers are computed in code; the model only reads what management said.</p>
        </div>
      )}
      {state.status === "error" && <div className="empty"><h2>Couldn't research that</h2>{state.error}</div>}
      {state.status === "ready" && <Research r={state.data} />}
    </div>
  );
}

const VERDICTS: [string, string, string][] = [
  ["delivered", "Delivered", "var(--up)"], ["partly", "Partly", "var(--amber)"], ["missed", "Missed", "var(--down)"],
  ["too_early", "Too early", "#9aa3b2"], ["unverifiable", "Can't verify", "#c4cad3"],
];

function Research({ r }: { r: any }) {
  const s = r.snapshot || {}, tr = r.trajectory || {}, bal = r.balance || {}, cash = r.cash || {};
  const total = r.promises?.length || 0;
  const q = (tr.quarterly || []).slice(-8);
  const maxSales = Math.max(...q.map((x: any) => x.sales || 0), 1);
  const dd = bal.working_capital?.["Debtor Days"] || bal.working_capital?.["Cash Conversion Cycle"];
  const transcriptUrl = (p: any) => (p.call_url ? `${p.call_url}${p.page ? `#page=${p.page}` : ""}` : null);

  return (
    <article>
      <div className="need-head" style={{ marginTop: 18 }}>
        <span className="sym" style={{ fontSize: 22 }}>{r.symbol}</span>
        <span className="cat">as of {r.as_of}</span>
      </div>
      <div className="muted small">{r.name}</div>
      {r.verdict && <p className="verdict">{r.verdict}</p>}

      {total > 0 && (
        <>
          <div className="section-title">Promised vs delivered <span className="faint">last {r.calls?.length} calls, {total} promises</span></div>
          <div className="tally" role="img" aria-label={VERDICTS.map(([k, l]) => `${r.tally?.[k] || 0} ${l}`).join(", ")}>
            {VERDICTS.map(([k, , c]) => r.tally?.[k] ? <i key={k} style={{ width: `${(r.tally[k] / total) * 100}%`, background: c }} /> : null)}
          </div>
          <div className="legend">{VERDICTS.filter(([k]) => r.tally?.[k]).map(([k, l, c]) => <span key={k}><b style={{ background: c }} />{r.tally[k]} {l.toLowerCase()}</span>)}</div>
          {r.promises.map((p: any) => (
            <div className="promise" key={p.id}>
              <div className="head">
                <span>{p.call} call · for {p.horizon || "unspecified"}{p.speaker ? ` · ${p.speaker}` : ""}</span>
                <span className={`v ${p.verdict}`}>{VERDICTS.find(([k]) => k === p.verdict)?.[1]}</span>
              </div>
              <q>{p.quote}</q>
              <div className="got">
                {p.actual ? <>Actual: <span className="num">{p.actual}</span></> : <span className="faint">No number to check yet</span>}
                {p.note && <span className="muted"> {p.note}</span>}
              </div>
              <div className="tiny faint" style={{ marginTop: 4 }}>
                {p.checked_by === "code" ? "Checked against reported numbers" : "Judged by the model from the numbers table"}
                {transcriptUrl(p) && <> · <a href={transcriptUrl(p)!} target="_blank" rel="noreferrer">Transcript p.{p.page}</a></>}
              </div>
            </div>
          ))}
        </>
      )}

      {r.narrative_vs_numbers?.length > 0 && (
        <>
          <div className="section-title">What they say, what the numbers say</div>
          {r.narrative_vs_numbers.map((n: any, i: number) => (
            <div className="vs" key={i}>
              <span className="mark" style={{ color: n.agree ? "var(--up)" : "var(--down)" }}>{n.agree ? "Agrees" : "Diverges"}</span>
              <span>{n.claim}</span><span className="muted">{n.reality}</span>
            </div>
          ))}
        </>
      )}

      <div className="section-title">Now</div>
      <div className="stats">
        <div><span className="num">{s.ttm_sales != null ? `₹${num(s.ttm_sales)}` : "–"}</span><span className="l">Sales, TTM (₹ cr)</span></div>
        <div><span className={`num ${s.last_q_sales_yoy > 0 ? "up" : s.last_q_sales_yoy < 0 ? "down" : ""}`}>{pct(s.last_q_sales_yoy)}</span><span className="l">{s.last_q} sales YoY</span></div>
        <div><span className="num">{pct(s.last_q_opm, 0, false)}</span><span className="l">{s.last_q} EBITDA margin</span></div>
        <div><span className="num">{s.pe != null ? num(s.pe, 1) : "–"}</span><span className="l">P/E</span></div>
        <div><span className="num">{pct(s.roce, 0, false)}</span><span className="l">ROCE</span></div>
        <div><span className={`num ${s.last_q_pat_yoy > 0 ? "up" : s.last_q_pat_yoy < 0 ? "down" : ""}`}>{pct(s.last_q_pat_yoy)}</span><span className="l">{s.last_q} PAT YoY</span></div>
      </div>

      {q.length > 2 && (
        <>
          <div className="section-title">Trajectory <span className="faint">quarterly sales</span></div>
          <div className="bars" aria-hidden="true">{q.map((x: any, i: number) => <i key={x.period} className={i === q.length - 1 ? "last" : ""} style={{ height: `${((x.sales || 0) / maxSales) * 100}%` }} />)}</div>
          <div className="axis"><span>{q[0].q}</span><span>{q[q.length - 1].q}</span></div>
          <p className="small muted">
            Sales {pct(tr.sales_cagr_3y)} a year over 3 years, profit {pct(tr.pat_cagr_3y)}.
            {tr.opm_change_3y != null && <> Margin {tr.opm_change_3y >= 0 ? "up" : "down"} {Math.abs(tr.opm_change_3y).toFixed(1)} points over the same period.</>}
          </p>
        </>
      )}

      <div className="section-title">Balance sheet and cash</div>
      <p className="small" style={{ marginTop: 4 }}>
        Debt to equity <b className="num">{bal.de ?? "–"}</b>{bal.de_3y_ago != null && <> (was {bal.de_3y_ago} three years ago)</>}.{" "}
        Operating cash was <b className="num">{cash.cfo_to_pat_3y != null ? `${cash.cfo_to_pat_3y}×` : "–"}</b> profit over 3 years
        {cash.cfo_to_pat_3y != null && (cash.cfo_to_pat_3y >= 0.9 ? ", so profits are turning into cash." : ", so profits are not fully turning into cash.")}
        {dd && dd.length > 1 && <> {Object.keys(bal.working_capital).includes("Debtor Days") ? "Debtor days" : "Cash conversion cycle"} {dd[0].value} → {dd[dd.length - 1].value}.</>}
      </p>

      {(r.bull?.length > 0 || r.bear?.length > 0) && (
        <div className="case">
          <div><h3 className="up">Bull</h3><ul>{r.bull.map((b: any, i: number) => <li key={i}>{b.point} <span className="cite">{b.cite}</span></li>)}</ul></div>
          <div><h3 className="down">Bear</h3><ul>{r.bear.map((b: any, i: number) => <li key={i}>{b.point} <span className="cite">{b.cite}</span></li>)}</ul></div>
        </div>
      )}

      {(r.business?.what_it_does || r.business?.about) && (
        <>
          <div className="section-title">The business</div>
          <p className="small" style={{ marginTop: 4 }}>{r.business.what_it_does || r.business.about}</p>
          {(r.business.ar_segments?.length ? r.business.ar_segments : r.business.segments)?.map((g: any) => (
            <div key={g.name} className="small muted">{g.name}: {g.revenue_share || g.share_or_growth}</div>
          ))}
        </>
      )}

      <div className="section-title">Sources</div>
      <ul className="sources" style={{ paddingLeft: 18, marginTop: 4 }}>
        {r.sources?.map((x: any) => <li key={x.url + x.label}><a href={x.url} target="_blank" rel="noreferrer">{x.label}</a></li>)}
      </ul>
      <p className="faint tiny">{r.discipline} Cost: {r.cost?.calls ?? 0} model calls, {num(r.cost?.tokens_in)} tokens in, {r.cost?.seconds}s.</p>
    </article>
  );
}
