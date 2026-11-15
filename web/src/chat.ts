/* Ask FINN: retrieval + an offline answerer.
   The app already holds every number FINN knows, so the client builds a compact, relevant
   context (only the companies the question names, the latest brief, recent alerts) and sends
   that to /api/chat. The server adds the key and the rules. When the model is unavailable,
   offlineAnswer() still answers the common questions straight from the data. */
import type { Data, Thresholds } from "./lib";
import { applyThresholds, CATEGORY_LABEL, pct, rs } from "./lib";

export type Msg = { role: "user" | "assistant"; content: string; mode?: "ai" | "offline"; symbols?: string[] };

/** Notes kept on this device when the Supabase memory store isn't connected. */
export const localNotes = {
  all: (): string[] => { try { return JSON.parse(localStorage.getItem("finn.notes") || "[]"); } catch { return []; } },
  set: (n: string[]) => { try { localStorage.setItem("finn.notes", JSON.stringify(n.slice(-50))); } catch { /* ignore */ } },
};
export function localMemoryCommand(q: string): string | null {
  const t = q.trim();
  let m = t.match(/^(?:please\s+)?(?:remember|note|keep in mind)(?:\s+that)?[:,]?\s+(.{3,})$/i);
  if (m) { const note = m[1].replace(/[.!]+$/, ""); localNotes.set([...localNotes.all(), note]); return `Noted on this device: "${note}". Connect Supabase to keep memory across devices.`; }
  if (/^what do you (remember|know about me)|^show (my )?memor/i.test(t)) {
    const n = localNotes.all();
    return n.length ? `I remember ${n.length} thing${n.length === 1 ? "" : "s"}:\n${n.map((x) => `• ${x}`).join("\n")}` : `Nothing yet. Tell me "remember that …".`;
  }
  m = t.match(/^forget(?:\s+about)?\s+(.+)$/i);
  if (m) {
    const all = localNotes.all();
    const keep = /^(everything|all)\b/i.test(m[1]) ? [] : all.filter((x) => !x.toLowerCase().includes(m![1].toLowerCase()));
    localNotes.set(keep);
    return all.length === keep.length ? `I don't have a note about "${m[1]}".` : `Done. Removed ${all.length - keep.length} note${all.length - keep.length === 1 ? "" : "s"}.`;
  }
  return null;
}

const researchCache = new Map<string, any>();
export async function loadResearch(sym: string): Promise<any | null> {
  if (researchCache.has(sym)) return researchCache.get(sym);
  try {
    const r = await fetch(`/data/research/${sym}.json`);
    const j = r.ok && r.headers.get("content-type")?.includes("json") ? await r.json() : null;
    researchCache.set(sym, j);
    return j;
  } catch {
    return null;
  }
}

/** Portfolio-wide questions shouldn't be narrowed to the company that happens to be on screen. */
export const isGeneral = (q: string) =>
  /today|holding|portfolio|which|\bany\b|\ball\b|this (month|week)|fell|fall|gain|loser|winner|red flag|results (were|this)|best|worst|moved|alerts?\b|remember|forget/i.test(q);

/** Symbols the question refers to, by ticker or by a word of the company name. */
export function mentioned(data: Data, q: string): string[] {
  const text = ` ${q.toUpperCase()} `;
  const out = new Set<string>();
  const names: Record<string, string> = {};
  for (const s of data.market?.stocks || []) names[s.symbol] = s.name;
  for (const [k, v] of Object.entries(data.researchIndex)) names[k] = v.name;
  for (const [sym, name] of Object.entries(names)) {
    if (new RegExp(`[^A-Z]${sym}[^A-Z]`).test(text)) out.add(sym);
    const first = (name || "").split(/\s+/)[0]?.toUpperCase();
    if (first && first.length > 3 && !["INDIA", "THE"].includes(first) && new RegExp(`[^A-Z]${first}[^A-Z]`).test(text)) out.add(sym);
  }
  return [...out];
}

const kept = (t: Record<string, number> = {}) => {
  const j = (t.delivered || 0) + (t.on_track || 0) + (t.partly || 0) + (t.behind || 0) + (t.missed || 0);
  return j ? Math.round((((t.delivered || 0) + (t.on_track || 0)) / j) * 100) : null;
};

function researchBlock(r: any): string {
  const s = r.snapshot || {};
  const lines = [
    `## ${r.symbol} (${r.name}) research, as of ${r.as_of}`,
    `Verdict: ${r.verdict || "n/a"}`,
    `Promises kept: ${kept(r.tally) ?? "n/a"}% of judged; tally ${JSON.stringify(r.tally || {})}`,
    `Snapshot: TTM sales ${rs(s.ttm_sales)}; ${s.last_q} sales YoY ${pct(s.last_q_sales_yoy)}; ${s.last_q} PAT YoY ${pct(s.last_q_pat_yoy)}; EBITDA margin ${pct(s.last_q_opm, 0, false)}; ROCE ${pct(s.roce, 0, false)}; P/E ${s.pe ?? "n/a"}; CFO/PAT 3y ${r.cash?.cfo_to_pat_3y ?? "n/a"}; D/E ${r.balance?.de ?? "n/a"}`,
    `Growth: sales CAGR 3y ${pct(r.trajectory?.sales_cagr_3y)}, PAT CAGR 3y ${pct(r.trajectory?.pat_cagr_3y)}`,
  ];
  const order = ["missed", "behind", "partly", "delivered", "on_track", "too_early", "unverifiable"];
  for (const p of [...(r.promises || [])].sort((a: any, b: any) => order.indexOf(a.verdict) - order.indexOf(b.verdict)).slice(0, 8))
    lines.push(`Promise [${p.verdict}] ${p.call} call, for ${p.horizon}: "${String(p.quote).slice(0, 140)}" -> actual: ${p.actual || "n/a"} (transcript p.${p.page ?? "?"})`);
  for (const n of r.narrative_vs_numbers || []) lines.push(`Narrative ${n.agree ? "agrees" : "diverges"}: ${n.claim} / numbers: ${n.reality}`);
  for (const b of r.bull || []) lines.push(`Bull: ${b.point}`);
  for (const b of r.bear || []) lines.push(`Bear: ${b.point}`);
  return lines.join("\n");
}

export async function buildContext(data: Data, q: string, t: Thresholds, focus: string | null): Promise<{ text: string; symbols: string[] }> {
  const syms = mentioned(data, q);
  if (focus && !syms.length && !isGeneral(q)) syms.push(focus);
  const parts: string[] = [];
  const asOf = data.market?.as_of;
  parts.push(`Data: prices as of close ${asOf}; filings to ${data.feed?.generated_at?.slice(0, 16)}. Portfolio of ${data.market?.stocks.length || 0} NSE stocks.`);
  const ln = localNotes.all();
  if (ln.length) parts.push(`User's notes: ${ln.join("; ")}`);

  const anchor = data.feed ? new Date(data.feed.generated_at).getTime() : Date.now();
  const recent = (data.feed?.items || []).filter((i) => anchor - new Date(i.filed_at).getTime() <= 7 * 864e5);
  const pick = syms.length ? (data.feed?.items || []).filter((i) => syms.includes(i.symbol)).slice(0, 10)
    : recent.filter((i) => i.tier !== "routine").sort((a, b) => b.score - a.score).slice(0, 12);
  parts.push("## Filings (newest relevant first)");
  for (const i of pick) {
    parts.push(`${i.symbol} | ${CATEGORY_LABEL[i.category] || i.category} | ${i.filed_at.slice(0, 10)} | ${i.tier} | ${i.results?.headline || i.summary || i.title}`
      + (i.management ? ` | people: ${i.management.people.map((p) => `${p.name} ${p.change} ${p.role}`).join("; ")}` : "")
      + (i.alert ? ` | stock ${pct(i.alert.pct_change)} on ${i.alert.date}` : ""));
  }

  parts.push(`## Prices at last close (${asOf})`);
  const stocks = data.market?.stocks || [];
  for (const s of (syms.length ? stocks.filter((x) => syms.includes(x.symbol)) : stocks))
    parts.push(`${s.symbol} (${s.name}, ${s.sector}): close ₹${s.close}, day ${pct(s.pct_change)}, volume ${s.vol_ratio?.toFixed(1)}x avg, ${pct(s.pct_from_52w_high)} from 52w high`);

  if (data.signals) {
    const hits = applyThresholds(data.signals.stocks, t, data.signals.overrides, data.signals.defaults).slice(0, 12);
    parts.push(`## Alerts with the user's thresholds (move ±${t.price_move_pct}%, volume ${t.volume_multiple}x, σ ${t.sigma_threshold ?? "off"})`);
    for (const h of hits) parts.push(`${h.date} ${h.symbol}: ${pct(h.pct)}, ${h.vol?.toFixed(1)}x volume (${h.triggers.join("+")})`);
  }

  const wantsAll = !syms.length && /compar|best|worst|which|rank|most|least|all companies|researched/i.test(q);
  const rsyms = wantsAll ? Object.keys(data.researchIndex) : syms.filter((s) => data.researchIndex[s]);
  for (const s of rsyms) {
    const r = await loadResearch(s);
    if (r) parts.push(researchBlock(r));
  }
  return { text: parts.join("\n").slice(0, 24000), symbols: syms };
}

/** Answers that don't need a model: the brief, one company, alerts, a comparison. */
export async function offlineAnswer(data: Data, q: string, t: Thresholds, focus: string | null): Promise<{ text: string; symbols: string[] }> {
  const syms = mentioned(data, q);
  if (!syms.length && focus && !isGeneral(q)) syms.push(focus);
  const ql = q.toLowerCase();

  const feed = data.feed?.items || [];
  const stocks = data.market?.stocks || [];
  const clean = (x: string) => x.replace(/\.+$/, "");
  const recent = (days: number) => {
    const a = data.feed ? new Date(data.feed.generated_at).getTime() : Date.now();
    return feed.filter((i) => a - new Date(i.filed_at).getTime() <= days * 864e5);
  };
  const scope = (list: typeof feed) => (syms.length ? list.filter((i) => syms.includes(i.symbol)) : list);

  // Two companies: side by side.
  if (syms.length >= 2 && /compar|vs\.?|versus|better|between/.test(ql)) {
    const rows: string[] = [];
    for (const sym of syms.slice(0, 3)) {
      const r = data.researchIndex[sym] ? await loadResearch(sym) : null;
      const s = stocks.find((x) => x.symbol === sym);
      if (r) rows.push(`${sym}: promises kept ${kept(r.tally) ?? "–"}%, sales ${pct(r.snapshot?.last_q_sales_yoy)} YoY, margin ${pct(r.snapshot?.last_q_opm, 0, false)}, ROCE ${pct(r.snapshot?.roce, 0, false)}, cash conversion ${r.cash?.cfo_to_pat_3y ?? "–"}×, P/E ${r.snapshot?.pe ?? "–"}`);
      else if (s) rows.push(`${sym}: last close ₹${s.close} (${pct(s.pct_change)}), ${pct(s.pct_from_52w_high)} from 52-week high; not researched yet`);
    }
    return { text: rows.join("\n"), symbols: syms };
  }

  // Filing types across the portfolio (or for the named company).
  const kinds: [RegExp, (i: (typeof feed)[number]) => boolean, string][] = [
    [/management|ceo|cfo|appoint|resign|director|board change|who joined|who left/, (i) => i.category === "management_change", "Management changes"],
    [/red flag|auditor|risk|warning|concern/, (i) => i.tags.includes("red_flag") || i.category === "litigation", "Red flags and regulatory items"],
    [/dividend|buyback|bonus|split/, (i) => ["dividend", "bonus_split"].includes(i.category) || /buyback/i.test(i.title), "Dividends, buybacks and splits"],
    [/order|contract|win|bag/, (i) => /order|contract/i.test(`${i.summary} ${i.title}`), "Orders and contracts"],
    [/acqui|merger|m&a|stake/, (i) => i.category === "M&A", "M&A"],
    [/fund ?rais|qip|ncd|debt issue|raise/, (i) => i.category === "fund_raise", "Fund raising"],
    [/rating/, (i) => i.category === "credit_rating", "Credit ratings"],
  ];
  for (const [re, test, title] of kinds) {
    if (re.test(ql)) {
      const hits = scope(recent(30)).filter(test).slice(0, 6);
      return hits.length
        ? { text: `${title}, last 30 days:\n${hits.map((i) => `• ${i.symbol} (${i.filed_at.slice(5, 10)}): ${clean(i.summary || i.title)}`).join("\n")}`, symbols: [...new Set(hits.map((i) => i.symbol))] }
        : { text: `No ${title.toLowerCase()} ${syms.length ? `for ${syms.join(", ")} ` : ""}in the last 30 days.`, symbols: syms };
    }
  }

  // Results across the portfolio.
  if (!syms.length && /result|earning|quarter|profit|revenue/.test(ql)) {
    const res = recent(30).filter((i) => i.results).sort((a, b) => (b.results!.rows.find((r) => r.key === "pat")?.yoy ?? -999) - (a.results!.rows.find((r) => r.key === "pat")?.yoy ?? -999));
    return { text: `Results filed in the last 30 days, by profit growth:\n${res.slice(0, 8).map((i) => `• ${i.symbol}: ${i.results!.headline}`).join("\n")}`, symbols: res.slice(0, 3).map((i) => i.symbol) };
  }

  // Price questions.
  if (!syms.length && /fell|fall|drop|down|worst|loser|declin/.test(ql)) {
    const l = [...stocks].sort((a, b) => (a.pct_change || 0) - (b.pct_change || 0)).slice(0, 5);
    return { text: `Biggest fallers at the ${data.market?.as_of} close: ${l.map((s) => `${s.symbol} ${pct(s.pct_change)}`).join(", ")}.`, symbols: l.slice(0, 3).map((s) => s.symbol) };
  }
  if (!syms.length && /rose|rise|gain|up the most|best perform|winner|top mover/.test(ql)) {
    const l = [...stocks].sort((a, b) => (b.pct_change || 0) - (a.pct_change || 0)).slice(0, 5);
    return { text: `Biggest gainers at the ${data.market?.as_of} close: ${l.map((s) => `${s.symbol} ${pct(s.pct_change)}`).join(", ")}.`, symbols: l.slice(0, 3).map((s) => s.symbol) };
  }
  if (!syms.length && /52|high|low/.test(ql)) {
    const near = [...stocks].sort((a, b) => (b.pct_from_52w_high ?? -999) - (a.pct_from_52w_high ?? -999));
    return { text: `Nearest their 52-week high: ${near.slice(0, 4).map((s) => `${s.symbol} (${pct(s.pct_from_52w_high)})`).join(", ")}. Furthest: ${near.slice(-3).map((s) => `${s.symbol} (${pct(s.pct_from_52w_high)})`).join(", ")}.`, symbols: near.slice(0, 2).map((s) => s.symbol) };
  }

  // One metric for one company.
  if (syms.length === 1 && data.researchIndex[syms[0]] && /roce|return on|margin|p\/?e|valuation|cash|debt|leverage|growth|cagr/.test(ql)) {
    const r = await loadResearch(syms[0]);
    if (r) {
      const s = r.snapshot || {};
      const bits = [] as string[];
      if (/roce|return on/.test(ql)) bits.push(`ROCE ${pct(s.roce, 0, false)}`);
      if (/margin/.test(ql)) bits.push(`EBITDA margin ${pct(s.last_q_opm, 0, false)} in ${s.last_q} (FY ${pct(s.fy_opm, 0, false)})`);
      if (/p\/?e|valuation/.test(ql)) bits.push(`P/E ${s.pe ?? "–"}`);
      if (/cash/.test(ql)) bits.push(`operating cash was ${r.cash?.cfo_to_pat_3y ?? "–"}× profit over 3 years`);
      if (/debt|leverage/.test(ql)) bits.push(`debt to equity ${r.balance?.de ?? "–"} (was ${r.balance?.de_3y_ago ?? "–"} three years ago)`);
      if (/growth|cagr/.test(ql)) bits.push(`sales ${pct(r.trajectory?.sales_cagr_3y)} a year over 3 years, ${pct(s.last_q_sales_yoy)} YoY in ${s.last_q}`);
      return { text: `${syms[0]}: ${bits.join("; ")}.`, symbols: syms };
    }
  }

  if (syms.length) {
    const out: string[] = [];
    for (const sym of syms.slice(0, 2)) {
      const r = data.researchIndex[sym] ? await loadResearch(sym) : null;
      const s = data.market?.stocks.find((x) => x.symbol === sym);
      const f = (data.feed?.items || []).filter((i) => i.symbol === sym);
      if (r) {
        const miss = (r.promises || []).filter((p: any) => p.verdict === "missed").slice(0, 2);
        out.push(`${sym}: ${kept(r.tally) ?? "–"}% of judged promises kept. ${r.verdict || ""}`.trim()
          + (miss.length ? ` Missed: ${miss.map((p: any) => `"${String(p.quote).slice(0, 70)}" (${p.actual})`).join("; ")}.` : "")
          + ` Latest quarter: sales ${pct(r.snapshot?.last_q_sales_yoy)} YoY, margin ${pct(r.snapshot?.last_q_opm, 0, false)}.`);
      } else if (s) {
        const res = f.find((i) => i.results);
        const other = f.find((i) => !i.results && i.tier !== "routine") || f.find((i) => !i.results);
        const clean = (x: string) => x.replace(/\.+$/, "");
        out.push((res ? `${sym} results (${res.filed_at.slice(0, 10)}): ${clean(res.results!.headline)}. ` : "")
          + `Last close ₹${s.close} (${pct(s.pct_change)}, ${s.vol_ratio?.toFixed(1)}× volume), ${pct(s.pct_from_52w_high)} from its 52-week high.`
          + (other ? ` Also filed (${other.filed_at.slice(0, 10)}): ${clean(other.summary || other.title)}.` : ""));
      } else out.push(`I don't have data on ${sym}.`);
    }
    return { text: out.join("\n\n"), symbols: syms };
  }

  if (/alert|move|moved|unusual|spike|volume|flag/.test(ql) && data.signals) {
    const last = data.signals.as_of;
    const hits = applyThresholds(data.signals.stocks, t, data.signals.overrides, data.signals.defaults);
    const today = hits.filter((h) => h.date === last);
    const top = [...(data.market?.stocks || [])].sort((a, b) => Math.abs(b.pct_change || 0) - Math.abs(a.pct_change || 0)).slice(0, 3);
    return { text: `At the ${last} close, ${today.length || "no"} holding${today.length === 1 ? "" : "s"} crossed your thresholds. `
      + `Biggest moves: ${top.map((s) => `${s.symbol} ${pct(s.pct_change)}`).join(", ")}. In the last month your settings flag ${hits.length} stock-days.`, symbols: top.map((s) => s.symbol) };
  }

  if (/compar|best|worst|which|rank|promise/.test(ql) && Object.keys(data.researchIndex).length) {
    const rows = Object.entries(data.researchIndex).map(([k, v]) => [k, kept(v.tally)] as const).sort((a, b) => (b[1] ?? -1) - (a[1] ?? -1));
    return { text: `Promise track record (delivered or on track, of those judged): ${rows.map(([k, v]) => `${k} ${v ?? "–"}%`).join(", ")}. `
      + `Open Research for the side-by-side charts.`, symbols: rows.slice(0, 2).map(([k]) => k) };
  }

  const anchor = data.feed ? new Date(data.feed.generated_at).getTime() : Date.now();
  const top = (data.feed?.items || []).filter((i) => anchor - new Date(i.filed_at).getTime() <= 3 * 864e5 && (i.tier !== "routine" || i.tags.includes("red_flag")))
    .sort((a, b) => b.score - a.score).slice(0, 3);
  if (top.length) {
    return { text: `What needs you: ${top.map((i) => `${i.symbol}: ${(i.results?.headline || i.summary || i.title).replace(/\.+$/, "")}`).join(". ")}.`, symbols: top.map((i) => i.symbol) };
  }
  return { text: "I can answer about today's filings, any holding (\"How did HAL do?\"), your alerts, or the researched companies (\"Did Kaynes keep its promises?\").", symbols: [] };
}

export function suggestions(focus: string | null, tab: string, researched: string[] = []): string[] {
  if (focus && !researched.includes(focus)) return [`How did ${focus} do?`, `What did ${focus} file recently?`, "What needs my attention today?"];
  if (focus) return [`Did ${focus} keep its promises?`, `What's the bear case on ${focus}?`, `How is ${focus}'s cash flow?`];
  if (tab === "alerts") return ["What moved at the last close?", "Which stocks keep getting flagged?", "Is anything moving without a filing?"];
  if (tab === "holdings") return ["Which holding fell the most?", "What did HAL file this week?", "Which stocks are near their 52-week high?"];
  return ["What needs my attention today?", "Did Kaynes keep its promises?", "Which company keeps its promises best?"];
}
