import { useMemo } from "react";
import type { Data, Thresholds } from "../lib";
import { applyThresholds, CATEGORY_LABEL, dayLabel, pct, times } from "../lib";

const CHOOSABLE = ["results", "M&A", "management_change", "litigation", "fund_raise", "pledging", "capex",
  "credit_rating", "insider_trading", "bonus_split", "dividend", "press_release"];

export function Alerts({ data, t, setT, careAbout, setCareAbout }: {
  data: Data; t: Thresholds; setT: (t: Thresholds) => void; careAbout: string[]; setCareAbout: (c: string[]) => void;
}) {
  const stocks = data.signals?.stocks || {};
  const sessions = Object.values(stocks)[0]?.length || 0;
  const hits = useMemo(() => applyThresholds(stocks, t, data.signals?.overrides, data.signals?.defaults), [stocks, t]);
  const lastClose = data.signals?.as_of;
  const today = hits.filter((h) => h.date === lastClose).length;
  const byDay = hits.reduce<Record<string, typeof hits>>((acc, h) => ((acc[h.date] ||= []).push(h), acc), {});
  const name = (s: string) => data.market?.stocks.find((x) => x.symbol === s)?.name || s;
  const toggle = (c: string) => setCareAbout(careAbout.includes(c) ? careAbout.filter((x) => x !== c) : [...careAbout, c]);
  const sigmaOn = t.sigma_threshold != null;

  return (
    <div className="screen">
      <p className="consequence">
        {hits.length === 0 ? "These settings would have stayed silent all month."
          : `These settings flag ${hits.length} stock-${hits.length === 1 ? "day" : "days"} in the last ${sessions} sessions${today ? `, ${today} on the last close` : ""}.`}
      </p>
      <p className="muted small" style={{ marginTop: 0 }}>
        You decide what counts as unusual. Drag a dial and the history below updates, so you can see how noisy it would be before you commit.
      </p>

      <div className="dial">
        <label htmlFor="mv">Daily move <span className="num">±{t.price_move_pct.toFixed(1)}%</span></label>
        <input id="mv" type="range" min={1} max={10} step={0.5} value={t.price_move_pct}
          onChange={(e) => setT({ ...t, price_move_pct: +e.target.value })} />
        <div className="hint">Close-to-close change on the day. Volatile names (set in portfolio.yaml) keep a proportionally looser bar.</div>
      </div>
      <div className="dial">
        <label htmlFor="vl">Volume <span className="num">{t.volume_multiple.toFixed(1)}× average</span></label>
        <input id="vl" type="range" min={1.2} max={5} step={0.1} value={t.volume_multiple}
          onChange={(e) => setT({ ...t, volume_multiple: +e.target.value })} />
        <div className="hint">Against the stock's own 20-day average, today excluded.</div>
      </div>
      <div className="dial">
        <label htmlFor="sg">
          Unusual for that stock
          <span className="num">{sigmaOn ? `${t.sigma_threshold!.toFixed(1)}σ` : "Off"}</span>
        </label>
        <input id="sg" type="range" min={1.5} max={5} step={0.5} value={t.sigma_threshold ?? 5} disabled={!sigmaOn}
          onChange={(e) => setT({ ...t, sigma_threshold: +e.target.value })} />
        <div className="hint">
          A 2.5% day is news for a sleepy bank and noise for a small-cap. This scales by each stock's own volatility.{" "}
          <button className="linkbtn" onClick={() => setT({ ...t, sigma_threshold: sigmaOn ? null : 3 })}>{sigmaOn ? "Turn off" : "Turn on"}</button>
        </div>
      </div>

      <div className="section-title">Filings that can reach the top of your brief</div>
      <div className="cats" role="group" aria-label="Filing categories">
        {CHOOSABLE.map((c) => (
          <button key={c} className="chip" aria-pressed={careAbout.includes(c)} onClick={() => toggle(c)}>{CATEGORY_LABEL[c]}</button>
        ))}
      </div>
      <p className="faint tiny">Red flags, such as an auditor resigning, always surface.</p>

      <div className="section-title">What these settings catch <span className="faint">{hits.length}</span></div>
      {Object.entries(byDay).map(([d, hs]) => (
        <div key={d}>
          <div className="daygroup">{dayLabel(d)}{d === lastClose ? ", last close" : ""}</div>
          {hs.map((h) => (
            <div className="hit" key={h.symbol + d}>
              <span><span className="sym">{h.symbol}</span> <span className="faint small">{name(h.symbol)}</span></span>
              <span className={`num ${h.pct && h.pct > 0 ? "up" : "down"}`}>{pct(h.pct)}</span>
              <span className="num">{times(h.vol)}</span>
              <span className="tr">
                {h.triggers.map((x) => (x === "move" ? "big move" : x === "volume" ? "volume spike" : `${Math.abs(h.sigma || 0).toFixed(1)}σ for this stock`)).join(" + ")}
              </span>
            </div>
          ))}
        </div>
      ))}
    </div>
  );
}
