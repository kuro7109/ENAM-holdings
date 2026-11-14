"""Pull side: research any NSE company from primary sources only.

  screener.in page  ->  standardised P&L / balance sheet / cash flow / ratios (from filings)
                    ->  links to concall transcripts + annual reports (company's own documents)
  transcripts       ->  extract tier: every quantified forward statement management made
  Python            ->  snapshot, trajectory, balance sheet, cash quality (no model needed)
  Python            ->  checks each promise it can against the actual numbers
  reason tier       ->  verdicts it can't compute, narrative vs numbers, bull / bear

The model never sees news, broker notes or its own memory of the company: every prompt says
so, and every claim it returns must point at a transcript page or a row of the numbers.
"""
from __future__ import annotations

import json
import logging
import re
import time
from datetime import date, datetime
from pathlib import Path
from typing import Callable

import requests
from bs4 import BeautifulSoup

from . import pdftext
from .announcements import BROWSER_HEADERS
from .cache import JsonCache
from .config import ROOT
from .llm import LLM

log = logging.getLogger(__name__)
IST = __import__("zoneinfo").ZoneInfo("Asia/Kolkata")
SCREENER = "https://www.screener.in/company/{sym}/{view}"
RESEARCH_DIR = ROOT / "data" / "research"


class ResearchError(RuntimeError):
    pass


# =========================================================================== screener
def _f(s):
    s = (s or "").replace(",", "").replace("%", "").replace("₹", "").replace("Cr.", "").strip()
    try:
        return float(s)
    except ValueError:
        return None


def _label(td) -> str:
    t = td.get_text(" ", strip=True).replace(" ", " ")
    return re.sub(r"\s*\+\s*$", "", t).strip()


def parse_table(section) -> dict | None:
    """-> {"periods": [...], "rows": {label: [float|None, ...]}}"""
    if section is None:
        return None
    table = section.find("table", class_="data-table") or section.find("table")
    if table is None:
        return None
    head = table.find("thead")
    periods = [th.get_text(" ", strip=True) for th in (head.find_all("th") if head else [])][1:]
    rows = {}
    for tr in (table.find("tbody") or table).find_all("tr"):
        tds = tr.find_all("td")
        if len(tds) < 2:
            continue
        label = _label(tds[0])
        if label and label not in rows:
            rows[label] = [_f(td.get_text(strip=True)) for td in tds[1:]]
    return {"periods": periods, "rows": rows} if periods and rows else None


def parse_screener(html: str, url: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    h1 = soup.find("h1")
    about = soup.select_one(".company-profile .about p") or soup.select_one("div.about p")
    key_points = soup.select_one(".company-profile .commentary") or soup.select_one("div.commentary")
    ratios = {}
    for li in soup.select("#top-ratios li"):
        name, val = li.select_one(".name"), li.select_one(".value")
        if name and val:
            nums = val.select(".number")  # "High / Low" has two numbers; take the first
            ratios[name.get_text(strip=True)] = _f(nums[0].get_text(strip=True) if nums
                                                   else val.get_text(" ", strip=True))

    tables = {k: parse_table(soup.find("section", id=k))
              for k in ("quarters", "profit-loss", "balance-sheet", "cash-flow", "ratios")}

    transcripts, annual_reports = [], []
    for li in soup.select(".concalls li"):
        when = li.find("div")
        for a in li.find_all("a"):
            if "transcript" in (a.get_text(" ", strip=True) + " " + (a.get("title") or "")).lower():
                transcripts.append({"month": when.get_text(strip=True) if when else "", "url": a.get("href")})
    for a in soup.select(".annual-reports li a"):
        label = a.find(string=True, recursive=False) or a.get_text(" ", strip=True)
        annual_reports.append({"label": str(label).strip(), "url": a.get("href")})

    return {
        "name": h1.get_text(strip=True) if h1 else None,
        "about": about.get_text(" ", strip=True) if about else None,
        "key_points": key_points.get_text(" ", strip=True)[:1200] if key_points else None,
        "ratios": ratios, "tables": tables, "transcripts": transcripts,
        "annual_reports": annual_reports, "url": url,
    }


def fetch_screener(symbol: str, session=None, cache: JsonCache | None = None) -> dict:
    s = session or requests.Session()
    cache = cache or JsonCache(ttl_seconds=12 * 3600)
    for view in ("consolidated/", ""):
        url = SCREENER.format(sym=symbol.upper(), view=view)
        hit = cache.get(url)
        html = hit
        if html is None:
            r = s.get(url, headers={**BROWSER_HEADERS, "Accept": "text/html"}, timeout=30)
            if r.status_code == 404:
                raise ResearchError(f"{symbol} not found on screener.in")
            r.raise_for_status()
            html = r.text
            cache.set(url, None, html)
        data = parse_screener(html, url)
        q = (data["tables"].get("quarters") or {})
        if len(q.get("periods", [])) >= 4 and q.get("rows"):
            data["view"] = "consolidated" if view else "standalone"
            return data
    raise ResearchError(f"no financial tables for {symbol} on screener.in")


# =========================================================================== numbers
MONTHS = {m: i for i, m in enumerate(["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct",
                                      "Nov", "Dec"], 1)}


def fy_quarter(label: str) -> str | None:
    """'Sep 2026' -> 'Q2 FY27' (Indian fiscal year starts in April)."""
    m = re.match(r"([A-Z][a-z]{2})\w*\s+(\d{4})", label or "")
    if not m or m.group(1) not in MONTHS:
        return None
    mon, yr = MONTHS[m.group(1)], int(m.group(2))
    q = {6: 1, 9: 2, 12: 3, 3: 4}.get(mon)
    if not q:
        return None
    fy = yr + 1 if mon >= 4 else yr
    return f"Q{q} FY{fy % 100:02d}"


def fy_label(label: str) -> str | None:
    m = re.match(r"Mar\w*\s+(\d{4})", label or "")
    return f"FY{int(m.group(1)) % 100:02d}" if m else None


def quarter_discussed(call_month: str) -> str | None:
    """A call in 'Nov 2026' discusses the quarter that ended before it: Sep 2026 -> Q2 FY27."""
    m = re.match(r"([A-Z][a-z]{2})\w*\s+(\d{4})", call_month or "")
    if not m or m.group(1) not in MONTHS:
        return None
    mon, yr = MONTHS[m.group(1)], int(m.group(2))
    ends = [(yr, 3), (yr, 6), (yr, 9), (yr - 1, 12), (yr - 1, 9), (yr, 12)]
    prior = max(((y, mm) for y, mm in ends if (y, mm) < (yr, mon)), default=None)
    if not prior:
        return None
    return fy_quarter(f"{list(MONTHS)[prior[1] - 1]} {prior[0]}")


def _row(t: dict | None, *names) -> list:
    if not t:
        return []
    for n in names:
        for k, v in t["rows"].items():
            if k.lower() == n.lower():
                return v
    for n in names:  # looser: startswith
        for k, v in t["rows"].items():
            if k.lower().startswith(n.lower()):
                return v
    return []


def _pct(a, b):
    if a is None or b is None or b <= 0:
        return None
    return round((a - b) / b * 100, 1)


def _cagr(end, start, years):
    if not end or not start or start <= 0 or end <= 0 or years <= 0:
        return None
    return round(((end / start) ** (1 / years) - 1) * 100, 1)


def quarterly_series(tables: dict) -> list[dict]:
    q = tables.get("quarters")
    if not q:
        return []
    sales = _row(q, "Sales", "Revenue")
    op = _row(q, "Operating Profit", "Financing Profit")
    opm = _row(q, "OPM %", "Financing Margin %")
    pat = _row(q, "Net Profit")
    out = []
    for i, p in enumerate(q["periods"]):
        g = lambda arr: arr[i] if i < len(arr) else None  # noqa: E731
        out.append({"period": p, "q": fy_quarter(p), "sales": g(sales), "op_profit": g(op),
                    "opm": g(opm), "pat": g(pat)})
    for i, r in enumerate(out):  # YoY vs four quarters back
        if i >= 4:
            r["sales_yoy"] = _pct(r["sales"], out[i - 4]["sales"])
            r["pat_yoy"] = _pct(r["pat"], out[i - 4]["pat"])
    return out


def annual_series(tables: dict) -> list[dict]:
    pl, bs, cf = tables.get("profit-loss"), tables.get("balance-sheet"), tables.get("cash-flow")
    if not pl:
        return []
    sales, opm, pat = _row(pl, "Sales", "Revenue"), _row(pl, "OPM %", "Financing Margin %"), _row(pl, "Net Profit")
    out = []
    for i, p in enumerate(pl["periods"]):
        g = lambda arr: arr[i] if i < len(arr) else None  # noqa: E731
        out.append({"period": p, "fy": fy_label(p) or p, "sales": g(sales), "opm": g(opm), "pat": g(pat)})

    def by_period(t, *names):
        if not t:
            return {}
        vals = _row(t, *names)
        return {p: (vals[i] if i < len(vals) else None) for i, p in enumerate(t["periods"])}

    borrow = by_period(bs, "Borrowings")
    eq_cap, reserves = by_period(bs, "Equity Capital"), by_period(bs, "Reserves")
    cfo, cfi = by_period(cf, "Cash from Operating Activity"), by_period(cf, "Cash from Investing Activity")
    for r in out:
        p = r["period"]
        r["borrowings"] = borrow.get(p)
        e = (eq_cap.get(p) or 0) + (reserves.get(p) or 0)
        r["equity"] = e or None
        r["de"] = round(r["borrowings"] / e, 2) if r.get("borrowings") is not None and e else None
        r["cfo"], r["cfi"] = cfo.get(p), cfi.get(p)
    for i, r in enumerate(out):
        if i >= 1 and "TTM" not in r["period"]:
            r["sales_growth"] = _pct(r["sales"], out[i - 1]["sales"])
    return out


def ratio_trend(tables: dict) -> dict:
    t = tables.get("ratios")
    if not t:
        return {}
    out = {}
    for name in ("Debtor Days", "Inventory Days", "Days Payable", "Cash Conversion Cycle",
                 "Working Capital Days", "ROCE %"):
        vals = _row(t, name)
        if vals:
            out[name] = [{"period": p, "value": vals[i] if i < len(vals) else None}
                         for i, p in enumerate(t["periods"])][-6:]
    return out


def compute_numbers(sc: dict) -> dict:
    q, a = quarterly_series(sc["tables"]), annual_series(sc["tables"])
    full = [r for r in a if "TTM" not in r["period"] and r["sales"] is not None]
    ttm = next((r for r in a if "TTM" in r["period"]), None)
    last = full[-1] if full else {}

    def cagr(key, n):
        if len(full) > n:
            return _cagr(full[-1][key], full[-1 - n][key], n)
        return None

    cash3 = full[-3:]
    sum_cfo = sum(r["cfo"] for r in cash3 if r.get("cfo") is not None)
    sum_pat = sum(r["pat"] for r in cash3 if r.get("pat") is not None)
    lq = q[-1] if q else {}
    snapshot = {
        "market_cap_cr": sc["ratios"].get("Market Cap"), "price": sc["ratios"].get("Current Price"),
        "pe": sc["ratios"].get("Stock P/E"), "roce": sc["ratios"].get("ROCE"), "roe": sc["ratios"].get("ROE"),
        "div_yield": sc["ratios"].get("Dividend Yield"),
        "ttm_sales": (ttm or {}).get("sales"), "ttm_pat": (ttm or {}).get("pat"),
        "last_q": lq.get("q"), "last_q_sales_yoy": lq.get("sales_yoy"), "last_q_pat_yoy": lq.get("pat_yoy"),
        "last_q_opm": lq.get("opm"), "fy_opm": last.get("opm"), "fy": last.get("fy"),
    }
    trajectory = {
        "sales_cagr_3y": cagr("sales", 3), "sales_cagr_5y": cagr("sales", 5),
        "pat_cagr_3y": cagr("pat", 3), "pat_cagr_5y": cagr("pat", 5),
        "opm_change_3y": (round(full[-1]["opm"] - full[-4]["opm"], 1)
                          if len(full) >= 4 and full[-1].get("opm") is not None and full[-4].get("opm") is not None
                          else None),
        "quarterly": q[-12:], "annual": full[-10:],
    }
    balance = {
        "borrowings": last.get("borrowings"), "equity": last.get("equity"), "de": last.get("de"),
        "de_3y_ago": full[-4]["de"] if len(full) >= 4 else None,
        "working_capital": ratio_trend(sc["tables"]),
    }
    cash = {
        "cfo_to_pat_3y": round(sum_cfo / sum_pat, 2) if sum_pat > 0 else None,
        "years": [{"fy": r["fy"], "cfo": r.get("cfo"), "pat": r.get("pat"), "cfi": r.get("cfi")} for r in full[-6:]],
    }
    return {"snapshot": snapshot, "trajectory": trajectory, "balance": balance, "cash": cash}


# =========================================================================== transcripts
GUIDANCE_SYSTEM = """You extract management guidance from an Indian listed company's earnings-call transcript.
Use ONLY this transcript. Do not use outside knowledge, news, or analyst estimates. Analysts'
questions are not guidance; only statements by company management count. Return JSON only."""

GUIDANCE_USER = """Company: {company}. Call held: {month} (discussing {quarter}).

1) guidance: every forward-looking statement by management about growth, margins, capex, debt,
   capacity, market share or other targets. Include directional ones ("double-digit growth").
   For each: {{"metric": "revenue_growth|volume_growth|ebitda_margin|gross_margin|pat_growth|capex|debt|capacity|other",
     "quote": "verbatim, <=35 words", "target_low": number|null, "target_high": number|null,
     "unit": "%|₹ cr|bps|x|other", "basis": "YoY|absolute|level", "horizon": "e.g. FY27, Q3 FY27, H2 FY27, next 2-3 years",
     "speaker": "name/role if given", "page": page number from the [page N] markers}}
2) delivery_comments: up to 4 things management said about how the quarter went versus what they
   expected earlier. Same quote/page format, plus "topic".
3) segments: business segments or revenue mix mentioned, as [{{"name": "...", "share_or_growth": "...", "page": n}}].
4) pushback: up to 3 topics analysts pressed hardest on, each <=12 words.
5) tone: one sentence, <=20 words.

JSON: {{"guidance": [...], "delivery_comments": [...], "segments": [...], "pushback": [...], "tone": "..."}}

--- transcript ---
{text}"""

VERDICT_SYSTEM = """You are a sceptical buy-side analyst comparing what management promised with what the
company delivered. Use ONLY the guidance quotes and the numbers table provided. No outside
knowledge, no news, no estimates. Every claim must cite either a guidance id (G#) or a numbers
row (e.g. "Q2 FY27 sales_yoy"). Be concise. Return JSON only."""

VERDICT_USER = """Company: {company}

NUMBERS (₹ crore; OPM = operating profit / sales, i.e. EBITDA margin; *_yoy in %):
{numbers}

GUIDANCE given on the last calls (id, call, metric, horizon, target, quote):
{guidance}

ALREADY CHECKED IN CODE (do not contradict these verdicts; you may add a note):
{checked}

WHAT MANAGEMENT LATER REPORTED on subsequent calls (use these to verify guidance the numbers table
can't show, e.g. volume growth, capacity, launches; cite as "<call> p<page>"):
{later}

Return JSON:
{{"promises": [{{"id": "G#", "verdict": "delivered|partly|missed|on_track|behind|too_early|unverifiable",
    "actual": "<=15 words with the number", "note": "<=20 words"}}],
  "narrative_vs_numbers": [{{"claim": "<=18 words, what management says", "reality": "<=18 words, what numbers show",
    "agree": true|false, "cite": "G# and/or numbers row"}}],
  "bull": [{{"point": "<=18 words", "cite": "..."}}],
  "bear": [{{"point": "<=18 words", "cite": "..."}}],
  "verdict": "<=28 words: does management do what it says?"}}
Use "unverifiable" only when neither the numbers nor a later management statement speaks to it.
Use on_track / behind when the promised period is partly reported.
Give one promises entry per G# not already checked in code; 2-4 narrative items; 3 bull and 3 bear points."""

AR_SYSTEM = """You describe a company's business from its own annual report text only. Return JSON only."""
AR_USER = """Company: {company}
From these annual-report pages, return:
{{"what_it_does": "<=35 words", "segments": [{{"name": "...", "revenue_share": "% or null", "note": "<=12 words"}}],
  "page_refs": [page numbers used]}}
--- annual report pages ---
{text}"""


GUIDANCE_KEYWORDS = [
    (r"guidance", 4), (r"\bguide", 3), (r"outlook", 3), (r"we expect", 3), (r"expect(?:ing|ed)? to", 2),
    (r"target", 2), (r"double[- ]digit", 3), (r"high single", 3), (r"margin", 1.5), (r"growth", 1),
    (r"capex", 2), (r"capacity", 1), (r"\bfy ?2?\d{2}\b", 1.5), (r"next (?:year|quarter|few)", 2),
    (r"going forward", 2), (r"sustain", 1), (r"band", 1), (r"range of", 1.5), (r"debt[- ]free|net cash", 1),
]


def _fy_of_quarter(qlabel: str) -> str | None:
    m = re.match(r"Q\d FY(\d{2})", qlabel or "")
    return f"FY{m.group(1)}" if m else None


def horizon_quarters(horizon: str) -> tuple[list[str], str] | None:
    """'Q3 FY27' -> (['Q3 FY27'], 'Q3 FY27'); 'H2 FY27' -> (['Q3 FY27','Q4 FY27'], ...); 'FY27' -> all four."""
    h = (horizon or "").upper().replace(" ", "").replace("'", "")
    m = re.fullmatch(r"(Q[1-4])FY(\d{2})", h)
    if m:
        return [f"{m.group(1)} FY{m.group(2)}"], f"{m.group(1)} FY{m.group(2)}"
    m = re.fullmatch(r"(H[12])FY(\d{2})", h)
    if m:
        qs = ["Q1", "Q2"] if m.group(1) == "H1" else ["Q3", "Q4"]
        return [f"{q} FY{m.group(2)}" for q in qs], f"{m.group(1)} FY{m.group(2)}"
    m = re.fullmatch(r"FY(\d{2})", h)
    if m:
        return [f"Q{i} FY{m.group(1)}" for i in range(1, 5)], f"FY{m.group(1)}"
    return None


def _prior(qlabel: str) -> str:
    q, fy = qlabel.split(" FY")
    return f"{q} FY{int(fy) - 1:02d}"


def check_in_code(g: dict, q: list[dict], a: list[dict]) -> dict | None:
    """Verdict for promises arithmetic can settle. For a period still in progress, judges the
    quarters reported so far: on_track / behind. Returns None when it needs judgment."""
    metric, lo, hi = g.get("metric"), g.get("target_low"), g.get("target_high")
    if lo is None and hi is None:
        return None
    lo = lo if lo is not None else hi
    if metric not in ("revenue_growth", "ebitda_margin", "pat_growth"):
        return None
    hz = horizon_quarters(g.get("horizon") or "")
    if not hz:
        return None
    wanted, label = hz
    by_q = {r.get("q"): r for r in q}
    got = [by_q[x] for x in wanted if x in by_q and by_q[x].get("sales") is not None]
    if not got:
        return {"verdict": "too_early", "actual": None, "where": None}
    complete = len(got) == len(wanted)
    span = label if complete else f"{' + '.join(r['q'].split(' ')[0] for r in got)} {label.split(' ')[-1]} so far"

    if metric == "ebitda_margin":
        sales = sum(r["sales"] for r in got)
        op = sum(r.get("op_profit") or 0 for r in got)
        if not sales or any(r.get("op_profit") is None for r in got):
            return None
        actual = round(op / sales * 100, 1)
        hit, partly = actual >= lo - 0.5, actual >= lo - 1.5
    else:
        key = "sales" if metric == "revenue_growth" else "pat"
        prev = [by_q.get(_prior(r["q"])) for r in got]
        if any(p is None or p.get(key) in (None, 0) for p in prev) or any(r.get(key) is None for r in got):
            return None
        now_v, then_v = sum(r[key] for r in got), sum(p[key] for p in prev)
        if then_v <= 0:
            return None
        actual = round((now_v - then_v) / then_v * 100, 1)
        hit, partly = actual >= lo, actual >= lo - max(2.0, abs(lo) * 0.2)
    if complete:
        verdict = "delivered" if hit else "partly" if partly else "missed"
    else:
        verdict = "on_track" if hit else "behind"
    what = "EBITDA margin" if metric == "ebitda_margin" else "sales growth" if metric == "revenue_growth" else "PAT growth"
    return {"verdict": verdict, "actual": f"{what} {actual:.1f}% ({span})", "actual_value": actual, "where": span}


def _numbers_text(q: list[dict], a: list[dict]) -> str:
    lines = ["quarter | sales | sales_yoy | opm | pat | pat_yoy"]
    for r in q[-12:]:
        lines.append(f"{r.get('q')} | {r.get('sales')} | {r.get('sales_yoy')} | {r.get('opm')} | {r.get('pat')} | {r.get('pat_yoy')}")
    lines.append("year | sales | sales_growth | opm | pat | cfo | borrowings")
    for r in a[-5:]:
        lines.append(f"{r.get('fy')} | {r.get('sales')} | {r.get('sales_growth')} | {r.get('opm')} | {r.get('pat')} | "
                     f"{r.get('cfo')} | {r.get('borrowings')}")
    return "\n".join(lines)


# =========================================================================== pipeline
def research(symbol: str, llm: LLM | None = None, n_calls: int = 4, with_ar: bool = False,
             progress: Callable[[str], None] = lambda s: None, fetch_pdf=pdftext.fetch_pdf,
             screener: Callable[[str], dict] = fetch_screener) -> dict:
    t0 = time.time()
    symbol = symbol.upper().strip()
    llm = llm or LLM()
    progress("Reading financials on screener.in")
    sc = screener(symbol)
    nums = compute_numbers(sc)
    q, a = nums["trajectory"]["quarterly"], nums["trajectory"]["annual"]
    company = sc.get("name") or symbol
    sources = [{"type": "financials", "label": f"screener.in ({sc.get('view')})", "url": sc["url"]}]

    # ---- transcripts -> guidance
    guidance, calls = [], []
    for t in sc["transcripts"][:n_calls]:
        quarter = quarter_discussed(t["month"]) or t["month"]
        progress(f"Reading {quarter} earnings call")
        pages = pdftext.pages_text(fetch_pdf(t["url"]))
        # Only the pages where management talks about the future: ~3x fewer tokens than the whole call.
        text = pdftext.best_pages(pages, GUIDANCE_KEYWORDS, k=12, max_chars=45_000)
        if not text:
            calls.append({"month": t["month"], "quarter": quarter, "url": t["url"], "status": "unreadable"})
            continue
        sources.append({"type": "transcript", "label": f"{quarter} call ({t['month']})", "url": t["url"]})
        out = llm.json("extract", GUIDANCE_SYSTEM, GUIDANCE_USER.format(
            company=company, month=t["month"], quarter=quarter, text=text), max_tokens=3000) or {}
        calls.append({"month": t["month"], "quarter": quarter, "url": t["url"], "status": "ok",
                      "tone": out.get("tone"), "pushback": out.get("pushback") or [],
                      "delivery_comments": out.get("delivery_comments") or [], "segments": out.get("segments") or []})
        for g in out.get("guidance") or []:
            g.update(call=quarter, call_url=t["url"])
            guidance.append(g)
    for i, g in enumerate(guidance, 1):
        g["id"] = f"G{i}"

    # ---- business snapshot (optional AR)
    business = {"about": sc.get("about"), "key_points": sc.get("key_points"),
                "segments": next((c["segments"] for c in calls if c.get("segments")), [])}
    if with_ar and sc["annual_reports"]:
        ar = sc["annual_reports"][0]
        progress(f"Reading {ar['label']} annual report")
        pages = pdftext.pages_text(fetch_pdf(ar["url"]), max_pages=250)
        text = pdftext.best_pages(pages, [(r"segment", 2), (r"revenue (?:mix|share)", 3), (r"business overview", 3),
                                          (r"management discussion", 2), (r"product portfolio", 2)], k=6)
        if text:
            out = llm.json("extract", AR_SYSTEM, AR_USER.format(company=company, text=text), max_tokens=900) or {}
            business.update(what_it_does=out.get("what_it_does"), ar_segments=out.get("segments") or [],
                            ar_pages=out.get("page_refs") or [], ar_url=ar["url"])
            sources.append({"type": "annual_report", "label": ar["label"], "url": ar["url"]})

    # ---- promises: code first, model for the rest
    progress("Checking promises against the numbers")
    checked = {}
    for g in guidance:
        c = check_in_code(g, q, a)
        if c:
            checked[g["id"]] = c
    analysis = {}
    if guidance or q:
        gtext = "\n".join(f"{g['id']} | {g['call']} | {g.get('metric')} | {g.get('horizon')} | "
                          f"{g.get('target_low')}-{g.get('target_high')} {g.get('unit') or ''} | \"{g.get('quote')}\""
                          for g in guidance) or "(no transcripts available)"
        ctext = "\n".join(f"{k}: {v['verdict']} ({v.get('actual')})" for k, v in checked.items()) or "(none)"
        later = "\n".join(f"{c['quarter']} call p{d.get('page')}: [{d.get('topic', '')}] \"{d.get('quote')}\""
                          for c in calls for d in (c.get("delivery_comments") or [])) or "(none)"
        progress("Weighing narrative against numbers")
        analysis = llm.json("reason", VERDICT_SYSTEM, VERDICT_USER.format(
            company=company, numbers=_numbers_text(q, a), guidance=gtext, checked=ctext, later=later),
            max_tokens=2500) or {}

    model_v = {p.get("id"): p for p in analysis.get("promises") or []}
    promises = []
    for g in guidance:
        c, m = checked.get(g["id"]), model_v.get(g["id"], {})
        promises.append({
            "id": g["id"], "call": g["call"], "call_url": g.get("call_url"), "page": g.get("page"),
            "metric": g.get("metric"), "horizon": g.get("horizon"), "quote": g.get("quote"),
            "speaker": g.get("speaker"), "target_low": g.get("target_low"), "target_high": g.get("target_high"),
            "unit": g.get("unit"),
            "verdict": (c or m).get("verdict") or "unverifiable",
            "actual": (c or {}).get("actual") or m.get("actual"),
            "note": m.get("note"), "checked_by": "code" if c else "model",
        })
    tally = {}
    for p in promises:
        tally[p["verdict"]] = tally.get(p["verdict"], 0) + 1

    return {
        "symbol": symbol, "name": company, "generated_at": datetime.now(IST).isoformat(timespec="seconds"),
        "as_of": date.today().isoformat(), "business": business, **nums,
        "calls": calls, "promises": promises, "tally": tally,
        "narrative_vs_numbers": analysis.get("narrative_vs_numbers") or [],
        "bull": analysis.get("bull") or [], "bear": analysis.get("bear") or [],
        "verdict": analysis.get("verdict"), "sources": sources,
        "cost": {**llm.usage.as_dict(), "seconds": round(time.time() - t0, 1)},
        "discipline": "Primary sources only: company filings via screener.in, earnings-call transcripts"
                      + (", annual report" if with_ar else "") + ". No news, broker notes or model memory.",
    }


def save(data: dict, out_dir: Path = RESEARCH_DIR) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    p = out_dir / f"{data['symbol']}.json"
    p.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    idx_p = out_dir / "index.json"
    idx = json.loads(idx_p.read_text(encoding="utf-8")) if idx_p.exists() else {}
    idx[data["symbol"]] = {"name": data["name"], "as_of": data["as_of"], "tally": data["tally"]}
    idx_p.write_text(json.dumps(idx, ensure_ascii=False, indent=1), encoding="utf-8")
    return p
