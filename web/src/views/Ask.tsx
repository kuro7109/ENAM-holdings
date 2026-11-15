import { useEffect, useRef, useState } from "react";
import { Row } from "../components/Cards";
import { HBars } from "../components/Charts";
import { Research } from "./Research";
import type { Data } from "../lib";
import { dayLabel, num, pct, tone } from "../lib";

const API = (import.meta.env.VITE_API_URL as string | undefined)?.replace(/\/$/, "");
type State = { status: "idle" } | { status: "running"; stage: string; symbol: string } | { status: "ready"; data: any }
  | { status: "error"; error: string } | { status: "missing"; symbol: string };

export function Ask({ data, symbol, setSymbol }: { data: Data; symbol: string | null; setSymbol: (s: string | null) => void }) {
  const [q, setQ] = useState(symbol || "");
  const [state, setState] = useState<State>({ status: "idle" });
  const run = useRef(0);

  useEffect(() => {
    if (!symbol) { run.current++; setState({ status: "idle" }); setQ(""); return; }
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
        setState({ status: "missing", symbol });
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
      {state.status !== "idle" && (
        <button className="backbtn" onClick={() => setSymbol(null)} aria-label="Back to all research">
          <span aria-hidden="true">‹</span> All research
        </button>
      )}
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
          {Object.keys(data.researchIndex).length > 1 && <Compare symbols={Object.keys(data.researchIndex)} onPick={setSymbol} />}
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
      {state.status === "missing" && <Missing symbol={state.symbol} data={data} onPick={setSymbol} />}
      {state.status === "ready" && <Research r={state.data} />}
    </div>
  );
}

/** Side-by-side: the same few measures for every researched company, ranked. */
function Compare({ symbols, onPick }: { symbols: string[]; onPick: (s: string) => void }) {
  const [rows, setRows] = useState<any[] | null>(null);
  useEffect(() => {
    let live = true;
    Promise.all(symbols.map((s) => fetch(`/data/research/${s}.json`).then((r) => (r.ok ? r.json() : null)).catch(() => null)))
      .then((all) => live && setRows(all.filter(Boolean)));
    return () => { live = false; };
  }, [symbols.join(",")]); // eslint-disable-line react-hooks/exhaustive-deps
  if (!rows) return <p className="faint small">Loading comparison…</p>;
  if (rows.length < 2) return null;
  const rec = (r: any) => {
    const t = r.tally || {}, judged = (t.delivered || 0) + (t.on_track || 0) + (t.partly || 0) + (t.behind || 0) + (t.missed || 0);
    return judged ? Math.round((((t.delivered || 0) + (t.on_track || 0)) / judged) * 100) : null;
  };
  const metric = (title: string, get: (r: any) => number | null, fmt: (v: number | null) => string, asc = false) => {
    const list = rows.map((r) => ({ key: r.symbol, label: r.symbol, value: get(r) }))
      .sort((a, b) => ((asc ? 1 : -1) * ((a.value ?? -1e9) - (b.value ?? -1e9))));
    return <HBars title={title} rows={list} fmt={fmt} onPick={onPick} />;
  };
  const p = (v: number | null) => (v == null ? "–" : `${v.toFixed(0)}%`);
  return (
    <section>
      <div className="section-title">Compare {rows.length} companies <span className="faint">tap one to open it</span></div>
      {metric("Promises kept (delivered or on track, of those judged)", rec, p)}
      <div className="charts-2">
        {metric("Sales growth, latest quarter YoY", (r) => r.snapshot?.last_q_sales_yoy ?? null, p)}
        {metric("EBITDA margin, latest quarter", (r) => r.snapshot?.last_q_opm ?? null, p)}
        {metric("Return on capital (ROCE)", (r) => r.snapshot?.roce ?? null, p)}
        {metric("Cash conversion, 3 yrs (CFO ÷ profit)", (r) => r.cash?.cfo_to_pat_3y ?? null, (v) => (v == null ? "–" : `${v.toFixed(2)}×`))}
      </div>
      {metric("Price to earnings (lower is cheaper)", (r) => r.snapshot?.pe ?? null, (v) => (v == null ? "–" : `${v.toFixed(0)}×`), true)}
    </section>
  );
}

/** A symbol with no saved research: show what FINN already knows, and where to go next. */
function Missing({ symbol, data, onPick }: { symbol: string; data: Data; onPick: (s: string) => void }) {
  const s = data.market?.stocks.find((x) => x.symbol === symbol);
  const filings = (data.feed?.items || []).filter((i) => i.symbol === symbol).slice(0, 4);
  const ready = Object.entries(data.researchIndex);
  return (
    <div className="empty" aria-live="polite">
      <h2>{symbol} hasn't been researched yet</h2>
      {s ? (
        <>
          <p className="small" style={{ margin: "4px 0 10px" }}>
            {s.name}: ₹{num(s.close, 1)} at the close of {dayLabel(s.date)},{" "}
            <span className={tone(s.pct_change)}>{pct(s.pct_change)}</span> on the day, {pct(s.pct_from_52w_high)} from its 52-week high.
          </p>
          {filings.length > 0 && (
            <>
              <div className="section-title">Its latest filings</div>
              <ul className="rows">{filings.map((i) => <Row key={i.id} item={i} />)}</ul>
            </>
          )}
        </>
      ) : (
        <p className="small" style={{ margin: "4px 0 10px" }}>It isn't in this portfolio, so there's no saved data for it here.</p>
      )}
      <p className="small muted" style={{ marginTop: 14 }}>
        The research engine works on any NSE symbol. In the repo, <code>python run_research.py {symbol}</code> builds this
        page in about a minute, from filings and earnings calls only.
      </p>
      {ready.length > 0 && (
        <>
          <div className="section-title">Ready now</div>
          <div className="cats">{ready.map(([k, v]) => <button key={k} className="chip" onClick={() => onPick(k)}>{k} <span className="faint">· {v.name}</span></button>)}</div>
        </>
      )}
    </div>
  );
}
