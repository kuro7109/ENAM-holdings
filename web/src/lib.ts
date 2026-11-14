/* Data loading, formatting and on-device settings. */

export type Signal = [string, number | null, number | null, number | null, number | null]; // date, close, pct, vol×, σ
export type Stock = {
  symbol: string; name: string; sector: string; date: string; close: number; pct_change: number | null;
  vol_ratio: number | null; sigma: number | null; high_52w: number; low_52w: number;
  pct_from_52w_high: number | null; spark: (number | null)[]; stale?: boolean;
};
export type ResultsRow = { metric: string; key: string; current: number | null; previous_quarter: number | null;
  year_ago_quarter: number | null; qoq: number | null; yoy: number | null };
export type Results = { statement: string; unit: string; is_lender: boolean; labels: Record<string, string>;
  rows: ResultsRow[]; margins: Record<string, Record<string, number | null>>; checks: string[]; headline: string;
  ebitda_note: string | null };
export type Person = { name: string; role: string; change: string; effective?: string | null; reason?: string | null;
  profile?: string | null; bio?: string; previous_employers?: string[]; bio_sources?: string[]; top_role?: boolean };
export type FeedItem = {
  id: string; symbol: string; name: string; sector: string; filed_at: string; category: string; tags: string[];
  title: string; pdf_url: string | null; summary: string | null; score: number; tier: "top" | "worth" | "routine";
  why: string[]; related: { id: string; title: string; pdf_url: string | null; filed_at: string }[];
  results?: Results; management?: { people: Person[] }; enriched?: string | null;
  alert?: { date: string; pct_change: number | null; vol_ratio: number | null; sigma: number | null; headline: string };
};
export type Data = {
  sample: boolean;
  market: { as_of: string; generated_at: string; stocks: Stock[] } | null;
  signals: { as_of: string; defaults: Thresholds; stocks: Record<string, Signal[]>;
    overrides?: Record<string, Partial<Thresholds>> } | null;
  feed: { generated_at: string; items: FeedItem[] } | null;
  researchIndex: Record<string, { name: string; as_of: string; tally: Record<string, number> }>;
};
export type Thresholds = { price_move_pct: number; volume_multiple: number; sigma_threshold: number | null };

async function get<T>(path: string): Promise<T | null> {
  try {
    const r = await fetch(path, { cache: "no-cache" });
    if (!r.ok) return null;
    return (await r.json()) as T;
  } catch {
    return null;
  }
}

export async function loadData(): Promise<Data> {
  const [market, signals, feed, researchIndex, sample] = await Promise.all([
    get<Data["market"]>("/data/out/market.json"),
    get<Data["signals"]>("/data/out/signals.json"),
    get<Data["feed"]>("/data/out/feed.json"),
    get<Data["researchIndex"]>("/data/research/index.json"),
    isSample(),
  ]);
  return { market, signals, feed, researchIndex: researchIndex || {}, sample };
}

async function isSample(): Promise<boolean> {
  try {
    const r = await fetch("/data/SAMPLE", { cache: "no-cache" });
    return r.ok && (await r.text()).trim() === "1";
  } catch {
    return false;
  }
}

// ------------------------------------------------------------------ settings (per device)
export const store = {
  get<T>(key: string, fallback: T): T {
    try {
      const v = localStorage.getItem("finn." + key);
      return v ? (JSON.parse(v) as T) : fallback;
    } catch {
      return fallback;
    }
  },
  set(key: string, value: unknown) {
    try {
      localStorage.setItem("finn." + key, JSON.stringify(value));
    } catch {
      /* private mode: settings just won't persist */
    }
  },
};

// ------------------------------------------------------------------ formatting
const inr = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 0 });
const inr1 = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 1 });
export const num = (x: number | null | undefined, d = 0) =>
  x == null || Number.isNaN(x) ? "–" : (d ? inr1 : inr).format(x);
export const pct = (x: number | null | undefined, d = 1, sign = true) =>
  x == null ? "–" : `${sign && x > 0 ? "+" : x < 0 ? "−" : ""}${Math.abs(x).toFixed(d)}%`;
export const times = (x: number | null | undefined) => (x == null ? "–" : `${x.toFixed(1)}×`);
export const tone = (x: number | null | undefined) => (x == null || x === 0 ? "" : x > 0 ? "up" : "down");

export function when(iso: string, now = Date.now()) {
  const d = new Date(iso);
  const mins = Math.round((now - d.getTime()) / 60000);
  const time = d.toLocaleTimeString("en-IN", { hour: "numeric", minute: "2-digit", hour12: false });
  if (mins < 60 * 18 && new Date(now).getDate() === d.getDate()) return `Today ${time}`;
  const day = d.toLocaleDateString("en-IN", { weekday: "short", day: "numeric", month: "short" });
  return `${day}, ${time}`;
}

export const dayLabel = (iso: string) =>
  new Date(iso + "T00:00:00").toLocaleDateString("en-IN", { weekday: "short", day: "numeric", month: "short" });

export const CATEGORY_LABEL: Record<string, string> = {
  results: "Results", "M&A": "M&A", fund_raise: "Fund raise", management_change: "Management change",
  litigation: "Litigation / regulatory", insider_trading: "Insider trade", earnings_call: "Earnings call",
  investor_meetings: "Investor meeting", credit_rating: "Credit rating", dividend: "Dividend",
  bonus_split: "Bonus / split", capex: "Capex", press_release: "Press release", postal_ballot: "Postal ballot",
  agm_egm: "AGM / EGM", pledging: "Promoter pledge", unclassified: "Paperwork",
};

// ------------------------------------------------------------------ alert rule (mirrors finn/prices.py)
export type Hit = { symbol: string; date: string; close: number | null; pct: number | null; vol: number | null;
  sigma: number | null; triggers: string[] };

/** Per-stock overrides from portfolio.yaml (e.g. SUZLON 6% vs 4% global) keep their ratio to the
 *  global setting, so moving the dial moves every stock's bar proportionally. */
export function applyThresholds(stocks: Record<string, Signal[]>, t: Thresholds,
  overrides: Record<string, Partial<Thresholds>> = {}, defaults?: Thresholds): Hit[] {
  const hits: Hit[] = [];
  for (const [symbol, rows] of Object.entries(stocks)) {
    const o = overrides[symbol] || {};
    const pm = o.price_move_pct && defaults?.price_move_pct ? t.price_move_pct * (o.price_move_pct / defaults.price_move_pct) : t.price_move_pct;
    const vm = o.volume_multiple && defaults?.volume_multiple ? t.volume_multiple * (o.volume_multiple / defaults.volume_multiple) : t.volume_multiple;
    for (const [date, close, p, v, s] of rows) {
      const tr: string[] = [];
      if (p != null && Math.abs(p) >= pm) tr.push("move");
      if (v != null && v >= vm) tr.push("volume");
      if (t.sigma_threshold && s != null && Math.abs(s) >= t.sigma_threshold && !tr.includes("move")) tr.push("sigma");
      if (tr.length) hits.push({ symbol, date, close, pct: p, vol: v, sigma: s, triggers: tr });
    }
  }
  return hits.sort((a, b) => (a.date < b.date ? 1 : a.date > b.date ? -1 : Math.abs(b.pct || 0) - Math.abs(a.pct || 0)));
}
