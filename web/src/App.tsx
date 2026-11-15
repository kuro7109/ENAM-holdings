import { useEffect, useState } from "react";
import type { Data, Thresholds } from "./lib";
import { applyThresholds, loadData, store, when } from "./lib";
import { Alerts } from "./views/Alerts";
import { Ask } from "./views/Ask";
import { Brief } from "./views/Brief";
import { Holdings } from "./views/Holdings";
import { ChatPage } from "./components/ChatPage";

type Tab = "brief" | "alerts" | "holdings" | "ask" | "chat";
const DEFAULT_CARE = ["results", "M&A", "management_change", "litigation", "fund_raise", "pledging", "capex"];

const Icon = ({ d }: { d: string }) => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d={d} /></svg>
);
const ICONS: Record<Tab, string> = {
  brief: "M5 4h14v16H5zM8 8h8M8 12h8M8 16h5",
  alerts: "M4 18h16M6 18V11a6 6 0 0 1 12 0v7M10 21h4",
  holdings: "M4 19l5-6 4 3 7-9M14 7h6v6",
  ask: "M11 4a7 7 0 1 0 0 14 7 7 0 0 0 0-14zM20 20l-4-4",
  chat: "M4 5h16v11H9l-5 4zM8 9h8M8 12h5",
};
const LABEL: Record<Tab, string> = { brief: "Brief", alerts: "Alerts", holdings: "Holdings", ask: "Research", chat: "Ask" };

export default function App() {
  const [data, setData] = useState<Data | null>(null);
  const TABS: Tab[] = ["brief", "alerts", "holdings", "ask", "chat"];
  // URL: #tab or #ask/SYMBOL. Every change is a history entry, so the phone's Back button steps
  // between tabs, and from a company back to the research home.
  const parse = (): { tab: Tab; sym: string | null } => {
    const [t, sym] = location.hash.slice(1).split("/");
    return { tab: TABS.includes(t as Tab) ? (t as Tab) : "brief", sym: t === "ask" && sym ? decodeURIComponent(sym).toUpperCase() : null };
  };
  const [tab, setTabState] = useState<Tab>(() => parse().tab);
  const setTab = (t: Tab) => {
    if (t === tab) return;
    history.pushState(null, "", `#${t}${t === "ask" && symbol ? `/${symbol}` : ""}`);
    setTabState(t);
  };
  const [lastVisit] = useState<number | null>(() => store.get<number | null>("lastVisit", null));
  const [seen, setSeen] = useState<Set<string>>(() => new Set(store.get<string[]>("seen", [])));
  const [care, setCare] = useState<string[]>(() => store.get("care", DEFAULT_CARE));
  const [t, setT] = useState<Thresholds | null>(() => store.get<Thresholds | null>("thresholds", null));
  const [symbol, setSymbolState] = useState<string | null>(() => parse().sym);
  const [chatFocus, setChatFocus] = useState<string | null>(null);
  const setSymbol = (s: string | null) => {
    history.pushState(null, "", s ? `#ask/${s}` : "#ask");
    setSymbolState(s);
    setTabState("ask");
  };

  useEffect(() => {
    loadData().then(setData);
    store.set("lastVisit", Date.now());
  }, []);
  useEffect(() => {
    if (!location.hash) history.replaceState(null, "", `#${tab}`);
    const onPop = () => { const p = parse(); setTabState(p.tab); if (p.tab === "ask") setSymbolState(p.sym); };
    window.addEventListener("popstate", onPop);
    window.addEventListener("hashchange", onPop);
    return () => { window.removeEventListener("popstate", onPop); window.removeEventListener("hashchange", onPop); };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { window.scrollTo(0, 0); }, [tab]);

  const thresholds: Thresholds = t || {
    price_move_pct: data?.signals?.defaults.price_move_pct ?? 4,
    volume_multiple: data?.signals?.defaults.volume_multiple ?? 2,
    sigma_threshold: data?.signals?.defaults.sigma_threshold ?? 3,
  };
  const saveT = (x: Thresholds) => { setT(x); store.set("thresholds", x); };
  const saveCare = (x: string[]) => { setCare(x); store.set("care", x); };
  const markSeen = (id: string) => setSeen((s) => { const n = new Set(s).add(id); store.set("seen", [...n].slice(-500)); return n; });
  const research = (s: string) => setSymbol(s);

  const flaggedToday = data?.signals ? applyThresholds(data.signals.stocks, thresholds, data.signals.overrides, data.signals.defaults).filter((h) => h.date === data.signals!.as_of).length : 0;

  return (
    <div className="app">
      <div className="top">
        <span className="wordmark">FINN</span>
        <span className="asof">{data?.feed ? `Updated ${when(data.feed.generated_at)}` : data ? "" : "Loading"}</span>
      </div>
      {data?.sample && (
        <div className="sample">Sample data: the backend hasn't published real filings yet. Every number here is illustrative.</div>
      )}
      {!data ? <div className="screen empty" aria-busy="true">Loading your brief</div> : (
        <main>
          {tab === "brief" && <Brief data={data} thresholds={thresholds} careAbout={care} seen={seen} markSeen={markSeen} lastVisit={lastVisit} />}
          {tab === "alerts" && <Alerts data={data} t={thresholds} setT={saveT} careAbout={care} setCareAbout={saveCare} />}
          {tab === "holdings" && <Holdings data={data} t={thresholds} onResearch={research} />}
          {tab === "ask" && <Ask data={data} symbol={symbol} setSymbol={setSymbol} />}
          {tab === "chat" && <ChatPage data={data} t={thresholds} focus={chatFocus} onOpen={research} />}
        </main>
      )}
      {data && tab !== "chat" && (
        <button className="fab" onClick={() => { setChatFocus(tab === "ask" ? symbol : null); setTab("chat"); }} aria-label="Ask FINN a question">
          <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 5h16v11H9l-5 4z" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinejoin="round" /></svg>
          Ask FINN
        </button>
      )}
      <nav className="tabs" aria-label="Sections">
        <div className="tabs-inner">
          {(Object.keys(LABEL) as Tab[]).map((k) => (
            <button key={k} className="tab" aria-current={tab === k ? "page" : undefined}
              onClick={() => { if (k === "chat") setChatFocus(null); setTab(k); }}>
              <Icon d={ICONS[k]} />
              {LABEL[k]}
              {k === "holdings" && flaggedToday > 0 && <span className="badge">{flaggedToday}</span>}
            </button>
          ))}
        </div>
      </nav>
    </div>
  );
}
