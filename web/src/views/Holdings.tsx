import { useEffect, useMemo, useRef, useState } from "react";
import { Row, Spark } from "../components/Cards";
import { HBars } from "../components/Charts";
import type { Data, Stock, Thresholds } from "../lib";
import { applyThresholds, dayLabel, num, pct, times, tone } from "../lib";

export function Holdings({ data, t, onResearch }: { data: Data; t: Thresholds; onResearch: (s: string) => void }) {
  const [open, setOpen] = useState<Stock | null>(null);
  const hits = useMemo(() => applyThresholds(data.signals?.stocks || {}, t, data.signals?.overrides, data.signals?.defaults), [data.signals, t]);
  const flagged = new Set(hits.filter((h) => h.date === data.signals?.as_of).map((h) => h.symbol));
  const stocks = [...(data.market?.stocks || [])].sort((a, b) => Math.abs(b.pct_change || 0) - Math.abs(a.pct_change || 0));
  const up = stocks.filter((s) => (s.pct_change || 0) > 0).length;

  if (!data.market) return <div className="screen empty"><h2>No prices yet</h2>Run <code>python run_daily.py</code>.</div>;

  return (
    <div className="screen">
      <header className="hero" style={{ paddingBottom: 6 }}>
        <h1 style={{ fontSize: 26 }}>{up} up, {stocks.length - up} down. <span className="quiet">{flagged.size} flagged.</span></h1>
        <p>Close of {dayLabel(data.market.as_of)}. Biggest moves first; a dot means it crossed your alert thresholds.</p>
      </header>
      <HBars title="Biggest moves at the last close" diverging polarity fmt={(v) => pct(v)}
        rows={stocks.slice(0, 6).map((x) => ({ key: x.symbol, label: x.symbol, value: x.pct_change }))}
        onPick={(k) => setOpen(stocks.find((x) => x.symbol === k) || null)} />
      <div className="section-title">All holdings <span className="faint">30-day trend</span></div>
      {stocks.map((s) => (
        <button key={s.symbol} className="holding" onClick={() => setOpen(s)}>
          <span style={{ minWidth: 0 }}>
            <span className="sym" style={{ fontSize: 15 }}>{s.symbol}</span>{flagged.has(s.symbol) && <span className="dot" aria-label="flagged" />}
            <span className="nm" style={{ display: "block" }}>{s.name}</span>
          </span>
          <Spark values={s.spark} />
          <span className="px">
            <span className={`num ${tone(s.pct_change)}`}>{pct(s.pct_change)}</span>
            <span className="num faint small">{times(s.vol_ratio)} vol</span>
          </span>
        </button>
      ))}
      {open && <StockSheet s={open} data={data} hits={hits.filter((h) => h.symbol === open.symbol)}
        onClose={() => setOpen(null)} onResearch={() => { setOpen(null); onResearch(open.symbol); }} />}
    </div>
  );
}

function StockSheet({ s, data, hits, onClose, onResearch }: {
  s: Stock; data: Data; hits: ReturnType<typeof applyThresholds>; onClose: () => void; onResearch: () => void;
}) {
  const filings = (data.feed?.items || []).filter((i) => i.symbol === s.symbol);
  const closeRef = useRef<HTMLButtonElement>(null);
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;
  useEffect(() => {
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";  // page behind the sheet doesn't scroll
    closeRef.current?.focus();
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onCloseRef.current(); };
    window.addEventListener("keydown", onKey);
    return () => { document.body.style.overflow = prev; window.removeEventListener("keydown", onKey); };
  }, []);
  const pos = s.high_52w > s.low_52w ? ((s.close - s.low_52w) / (s.high_52w - s.low_52w)) * 100 : 50;
  return (
    <div className="sheet-back" onClick={onClose} role="dialog" aria-modal="true" aria-label={s.name}>
      <div className="sheet" onClick={(e) => e.stopPropagation()}>
        <div className="grabber" />
        <div className="need-head">
          <span className="sym" style={{ fontSize: 22 }}>{s.symbol}</span>
          <button ref={closeRef} className="linkbtn" onClick={onClose}>Close</button>
        </div>
        <div className="muted small">{s.name} · {s.sector}</div>
        <div className="stats">
          <div><span className="num">₹{num(s.close, 1)}</span><span className="l">Close</span></div>
          <div><span className={`num ${tone(s.pct_change)}`}>{pct(s.pct_change)}</span><span className="l">On the day</span></div>
          <div><span className="num">{pct(s.pct_from_52w_high)}</span><span className="l">From 52-week high</span></div>
        </div>
        <div className="range52" aria-label="52-week range"><i style={{ left: `calc(${pos}% - 1px)` }} /></div>
        <div className="axis num"><span>₹{num(s.low_52w)}</span><span>52 weeks</span><span>₹{num(s.high_52w)}</span></div>
        <div style={{ marginTop: 14 }}><Spark values={s.spark} w={320} h={60} /></div>
        <div className="faint tiny">Last 30 sessions</div>

        {hits.length > 0 && (
          <>
            <div className="section-title">Flagged days</div>
            {hits.slice(0, 6).map((h) => (
              <div className="hit" key={h.date}>
                <span>{dayLabel(h.date)}</span>
                <span className={`num ${tone(h.pct)}`}>{pct(h.pct)}</span>
                <span className="num">{times(h.vol)}</span>
              </div>
            ))}
          </>
        )}
        <div className="section-title">Filings <span className="faint">{filings.length}</span></div>
        {filings.length ? <ul className="rows">{filings.map((i) => <Row key={i.id} item={i} />)}</ul>
          : <p className="muted small">Nothing filed in the last 30 days.</p>}
        <div style={{ marginTop: 18, display: "flex", gap: 8 }}>
          <button className="btn" onClick={onResearch}>Research {s.symbol}</button>
        </div>
      </div>
    </div>
  );
}
