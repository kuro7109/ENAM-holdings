import { useMemo, useState } from "react";
import { MoveItem, NeedItem, Row } from "../components/Cards";
import type { Data, FeedItem, Thresholds } from "../lib";
import { applyThresholds, CATEGORY_LABEL } from "../lib";
import { success } from "../press";

type Win = { key: string; label: string; hours: number };
const H = 3600_000;

export function Brief({ data, thresholds, careAbout, seen, markSeen, lastVisit }: {
  data: Data; thresholds: Thresholds; careAbout: string[]; seen: Set<string>;
  markSeen: (id: string) => void; lastVisit: number | null;
}) {
  const now = Date.now();
  const windows: Win[] = useMemo(() => {
    const w: Win[] = [];
    if (lastVisit && now - lastVisit > H && now - lastVisit < 14 * 24 * H)
      w.push({ key: "since", label: "Since you last looked", hours: (now - lastVisit) / H });
    w.push({ key: "24h", label: "24 hours", hours: 24 }, { key: "3d", label: "3 days", hours: 72 },
      { key: "7d", label: "7 days", hours: 168 }, { key: "30d", label: "30 days", hours: 720 });
    return w;
  }, [lastVisit]); // eslint-disable-line react-hooks/exhaustive-deps

  const [picked, setPicked] = useState<string | null>(null);
  const [leaving, setLeaving] = useState<string | null>(null);
  const [showRoutine, setShowRoutine] = useState(false);
  const [showCleared, setShowCleared] = useState(false);
  const items = data.feed?.items || [];
  // Fixed windows count back from the last data refresh (shown in the header), so the brief
  // still makes sense on a weekend or days after the last run. "Since you last looked" is real time.
  const anchor = data.feed ? new Date(data.feed.generated_at).getTime() : now;
  const inWin = (w: Win) => items.filter((i) => {
    const t = new Date(i.filed_at).getTime();
    return w.key === "since" ? t >= (lastVisit || 0) : anchor - t <= w.hours * H;
  });

  // The user's view of priority: categories they care about can reach the top; red flags always do.
  const care = new Set(careAbout);
  const tierOf = (i: FeedItem) =>
    i.tags.includes("red_flag") || (care.has(i.category) && i.score >= 55) ? "top"
      : i.score >= 30 && !i.tags.includes("routine") ? "worth" : "routine";

  // Default window: since last visit, else 24h. If nothing important is in it and the user didn't
  // choose it, widen to the first window (up to 7 days) that has something that needs them.
  let win = windows.find((w) => w.key === picked) || windows[0];
  let widenedFrom: { w: Win; n: number } | null = null;
  if (!picked && !inWin(win).some((i) => tierOf(i) === "top")) {
    const next = windows.find((w) => w.hours <= 168 && w.hours > win.hours && inWin(w).some((i) => tierOf(i) === "top"));
    if (next) { widenedFrom = { w: win, n: inWin(win).length }; win = next; }
  }
  const filings = inWin(win);

  // Price/volume moves on the last close that no filing explains.
  const asOf = data.signals?.as_of;
  const moves = useMemo(() => {
    if (!data.signals || !asOf) return [];
    const explained = new Set(items.filter((i) => i.alert?.date === asOf || i.filed_at.slice(0, 10) === asOf).map((i) => i.symbol));
    return applyThresholds(data.signals.stocks, thresholds, data.signals.overrides, data.signals.defaults).filter((h) => h.date === asOf && !explained.has(h.symbol));
  }, [data.signals, thresholds, items, asOf]);
  const movesInWin = asOf && now - new Date(asOf + "T15:30:00+05:30").getTime() <= Math.max(win.hours, 24) * H ? moves : [];

  const top = filings.filter((i) => tierOf(i) === "top").sort((a, b) => b.score - a.score);
  const worth = filings.filter((i) => tierOf(i) === "worth").sort((a, b) => b.score - a.score);
  const routine = filings.filter((i) => tierOf(i) === "routine");
  const openTop = top.filter((i) => !seen.has(i.id));
  const openMoves = movesInWin.filter((m) => !seen.has(`move:${m.symbol}:${m.date}`));
  const cleared = top.filter((i) => seen.has(i.id));
  const need = openTop.length + openMoves.length;
  const rest = worth.length + routine.length;

  const done = (id: string) => {
    success(document.querySelector(".hero h1"));  // the count drops: small pop + firmer buzz
    setLeaving(id);
    window.setTimeout(() => { markSeen(id); setLeaving(null); }, 260);
  };

  const routineMix = Object.entries(routine.reduce<Record<string, number>>((acc, i) => {
    const k = i.tags.includes("newspaper_ad") ? "newspaper ads" : i.tags.includes("intimation") ? "meeting notices"
      : i.category === "unclassified" || i.tags.includes("routine") ? "paperwork" : (CATEGORY_LABEL[i.category] || i.category).toLowerCase();
    acc[k] = (acc[k] || 0) + 1;
    return acc;
  }, {})).sort((a, b) => b[1] - a[1]);

  if (!data.feed) {
    return (
      <div className="screen empty">
        <h2>No filings yet</h2>
        Run <code>python run_daily.py --days 30</code> and push <code>data/out</code>. The brief builds itself from it.
      </div>
    );
  }

  return (
    <div className="screen">
      <header className="hero">
        <h1>
          {need === 0 ? <>You're clear.</> : <>{need} {need === 1 ? "thing needs" : "things need"} you.</>}{" "}
          <span className="quiet">{rest === 0 ? "Nothing else filed." : `${rest} ${rest === 1 ? "filing doesn't" : "filings don't"}.`}</span>
        </h1>
        <p>
          {widenedFrom ? `${widenedFrom.w.key === "since" ? "Quiet since you last looked" : `Quiet ${widenedFrom.w.label.toLowerCase()}`}${widenedFrom.n ? ` (${widenedFrom.n} routine ${widenedFrom.n === 1 ? "filing" : "filings"})` : ""}, so this covers the last ${win.label.toLowerCase()}. ` : ""}
          Across {data.market?.stocks.length || "your"} holdings. Ranked by what can move a stock; paperwork is folded away.
        </p>
      </header>

      <div className="windows" role="group" aria-label="Time window">
        {windows.map((w) => (
          <button key={w.key} className="chip" aria-pressed={w.key === win.key} onClick={() => setPicked(w.key)}>
            {w.label}
          </button>
        ))}
      </div>

      {filings.length === 0 && movesInWin.length === 0 && (
        <div className="empty">
          <h2>Nothing filed in the last {win.label.toLowerCase()}</h2>
          <button className="linkbtn" onClick={() => setPicked("7d")}>Show the last 7 days</button>
        </div>
      )}

      {openMoves.map((m) => {
        const id = `move:${m.symbol}:${m.date}`;
        const s = data.market?.stocks.find((x) => x.symbol === m.symbol);
        return <MoveItem key={id} symbol={m.symbol} name={s?.name || m.symbol} pctChange={m.pct} vol={m.vol}
          sigma={m.sigma} onDone={() => done(id)} leaving={leaving === id} />;
      })}
      {openTop.map((i) => <NeedItem key={i.id} item={i} onDone={() => done(i.id)} leaving={leaving === i.id} />)}

      {worth.length > 0 && (
        <>
          <div className="section-title">Worth a look <span className="faint">{worth.length}</span></div>
          <ul className="rows">{worth.map((i) => <Row key={i.id} item={i} />)}</ul>
        </>
      )}

      {routine.length > 0 && (
        <>
          <div className="section-title">Folded</div>
          <button className="fold" onClick={() => setShowRoutine(!showRoutine)} aria-expanded={showRoutine}>
            <span><b>{routine.length} routine {routine.length === 1 ? "filing" : "filings"}.</b> {routineMix.slice(0, 3).map(([k, v]) => `${v} ${k}`).join(", ")}{routineMix.length > 3 ? ", …" : ""}</span>
            <span className="linkbtn">{showRoutine ? "Hide" : "Show"}</span>
          </button>
          {showRoutine && <ul className="rows">{routine.map((i) => <Row key={i.id} item={i} />)}</ul>}
        </>
      )}

      {cleared.length > 0 && (
        <>
          <button className="fold" style={{ marginTop: 14 }} onClick={() => setShowCleared(!showCleared)} aria-expanded={showCleared}>
            <span><b>{cleared.length} done.</b> {cleared.length === 1 ? "An item" : "Items"} you've already cleared.</span>
            <span className="linkbtn">{showCleared ? "Hide" : "Show"}</span>
          </button>
          {showCleared && <ul className="rows">{cleared.map((i) => <Row key={i.id} item={i} />)}</ul>}
        </>
      )}
    </div>
  );
}
