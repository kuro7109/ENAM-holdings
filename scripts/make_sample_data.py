#!/usr/bin/env python3
"""Sample data for building the UI offline. Runs the REAL pipeline functions (signals, alerts,
classifier, results-card maths, feed ranking) on synthetic inputs and writes to web/sample/.

Never written to data/out: the app labels sample data clearly and only uses it when real data
is missing.   python scripts/make_sample_data.py
"""
from __future__ import annotations

import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from finn import prices as px  # noqa: E402
from finn import research as R  # noqa: E402
from finn.classify import classify, is_material  # noqa: E402
from finn.config import load_config  # noqa: E402
from finn.enrich import build_feed, build_results_card  # noqa: E402

OUT = ROOT / "web" / "sample"
rng = np.random.default_rng(7)
cfg = load_config()
AS_OF = date(2026, 11, 13)


def prices(sym: str, base: float, vol: float, shock: dict) -> pd.DataFrame:
    days = pd.bdate_range(end=AS_OF, periods=260)
    r = rng.normal(0.0004, vol, len(days))
    v = rng.lognormal(0, 0.25, len(days))
    for back, (ret, vmul) in shock.items():
        r[-back] = ret
        v[-back] *= vmul
    close = base * np.exp(np.cumsum(r))
    vol_ = (v * 1_000_000).round()
    return pd.DataFrame({"open": close, "high": close * 1.01, "low": close * 0.99, "close": close,
                         "adj_close": close, "volume": vol_}, index=days)


SHOCKS = {"TRENT": {1: (-0.071, 3.4)}, "DIXON": {1: (0.058, 2.6)}, "TITAN": {2: (0.021, 2.4)},
          "HDFCBANK": {1: (0.024, 1.3)}, "SUZLON": {3: (0.072, 3.8)}, "INFY": {6: (0.045, 2.2)},
          "POLYCAB": {1: (-0.028, 2.1)}}
market, alerts, signals = [], [], {}
for c in cfg.companies:
    df = prices(c.symbol, rng.uniform(150, 9000), 0.022 if c.symbol in ("SUZLON", "IRFC", "DIXON") else 0.011,
                SHOCKS.get(c.symbol, {}))
    a_cfg = cfg.alerts_for(c.symbol)
    sig = px.compute_signals(df, a_cfg)
    s = px.snapshot(c.symbol, sig)
    s.update(name=c.name, sector=c.sector, stale=False)
    market.append(s)
    signals[c.symbol] = px.signal_history(sig, 22)
    for a in px.detect_alerts(c.symbol, sig, a_cfg, last_n=22):
        a.update(name=c.name, sector=c.sector)
        alerts.append(a)
alerts.sort(key=lambda a: a["date"], reverse=True)

F = [  # (symbol, days_ago, hour, exchange category, subject)
    ("TRENT", 1, "17:40", "Financial Results", "Financial Results for the quarter ended September 30, 2026"),
    ("TRENT", 1, "17:52", "Press Release", "Press release on financial results for Q2 FY27"),
    ("TRENT", 1, "18:05", "Investor Presentation", "Investor presentation Q2 FY27"),
    ("TITAN", 2, "16:20", "Change in Management", "Appointment of Mr. Arvind Rao as Chief Financial Officer"),
    ("DIXON", 1, "19:10", "Acquisition", "Acquisition of 51% stake in a display module maker"),
    ("POLYCAB", 1, "11:05", "Change in Auditors", "Resignation of Statutory Auditor"),
    ("HDFCBANK", 3, "18:30", "Financial Results", "Unaudited financial results for the quarter ended 30 September 2026"),
    ("LT", 2, "09:15", "Press Release", "L&T bags 'mega' order for a hydro power project in the Middle East"),
    ("BAJFINANCE", 4, "12:00", "Credit Rating", "CRISIL reaffirms AAA/Stable rating on NCDs"),
    ("SUNPHARMA", 5, "20:00", "Regulatory", "Receipt of warning letter from USFDA for Halol facility"),
    ("ITC", 2, "15:00", "Dividend", "Record date for interim dividend of Rs 6.50 per share"),
    ("INFY", 6, "16:00", "Buyback", "Board approves buyback of equity shares through tender offer"),
    ("SUZLON", 3, "10:30", "Press Release", "Suzlon secures 381 MW order from a leading IPP"),
    ("MARUTI", 1, "09:00", "Board Meeting", "Board meeting intimation to consider financial results"),
    ("ASIANPAINT", 1, "18:00", "Newspaper Publication", "Copy of newspaper publication of financial results"),
    ("RELIANCE", 2, "14:00", "Trading Window", "Closure of trading window"),
    ("HAL", 3, "17:00", "Investor Meet", "Schedule of analyst / institutional investor meet"),
    ("PERSISTENT", 2, "13:00", "ESOP", "Allotment of equity shares under ESOP scheme"),
    ("BHARTIARTL", 4, "18:00", "Earnings Call", "Transcript of the earnings call for Q2 FY27"),
    ("IRFC", 1, "12:30", "Shareholders meeting", "Voting results of postal ballot"),
    ("LT", 4, "11:00", "Compliance", "Compliance certificate under Regulation 74(5)"),
    ("TITAN", 5, "10:00", "Analysts/Institutional Investor Meet", "Intimation of investor conference participation"),
    ("POLYCAB", 6, "17:00", "Financial Results", "Audited financial results for the quarter ended September 30, 2026"),
    ("ITC", 7, "16:00", "Shareholding", "Shareholding pattern for the quarter ended September 2026"),
]
items = []
for i, (sym, ago, hh, cat, subj) in enumerate(F):
    d = AS_OF - timedelta(days=ago)
    row = {"id": f"s{i:02d}", "symbol": sym, "company": next(c.name for c in cfg.companies if c.symbol == sym),
           "source": "NSE", "filed_at": f"{d.isoformat()}T{hh}:00+05:30", "exchange_category": cat,
           "subject": subj, "pdf_url": "https://www.nseindia.com/companies-listing/corporate-filings-announcements"}
    row.update(classify(cat, subj))
    row["material"] = is_material(row["category"], row["tags"])
    items.append(row)

store = {
    "s00": {"status": "ok", "kind": "results", "results": build_results_card({
        "statement": "consolidated", "unit": "₹ crore", "is_lender": False,
        "labels": {"current": "Q2 FY27", "previous_quarter": "Q1 FY27", "year_ago_quarter": "Q2 FY26"},
        "current": {"revenue": 5210, "other_income": 62, "finance_costs": 118, "depreciation": 340, "pbt": 482, "pat": 352},
        "previous_quarter": {"revenue": 5080, "other_income": 70, "finance_costs": 112, "depreciation": 322, "pbt": 541, "pat": 401},
        "year_ago_quarter": {"revenue": 4157, "other_income": 58, "finance_costs": 104, "depreciation": 270, "pbt": 450, "pat": 335}})},
    "s03": {"status": "ok", "kind": "management", "summary": "Arvind Rao named CFO from 1 Dec; succeeds Ashok Sonthalia, retiring",
            "management": {"people": [
                {"name": "Arvind Rao", "role": "Chief Financial Officer", "change": "appointed", "effective": "1 December 2026",
                 "top_role": True, "profile": None,
                 "bio": "Finance leader with 22 years across consumer and retail; previously CFO of a listed consumer-durables maker and finance head at a multinational FMCG company. Chartered Accountant.",
                 "previous_employers": ["Consumer durables (listed)", "MNC FMCG"], "bio_sources": ["https://www.linkedin.com/"]},
                {"name": "Ashok Sonthalia", "role": "Chief Financial Officer", "change": "retired", "effective": "30 November 2026",
                 "top_role": True, "profile": None}]}},
    "s04": {"status": "ok", "kind": "generic", "summary": "Buys 51% of a display-module maker for ₹410 cr; adds backward integration for TVs",
            "importance": 5, "category": "M&A"},
    "s05": {"status": "ok", "kind": "generic", "summary": "Statutory auditor resigns mid-term citing 'pre-occupation'; no other reason given",
            "importance": 5},
    "s06": {"status": "ok", "kind": "results", "results": build_results_card({
        "statement": "standalone", "unit": "₹ crore", "is_lender": True,
        "labels": {"current": "Q2 FY27", "previous_quarter": "Q1 FY27", "year_ago_quarter": "Q2 FY26"},
        "current": {"revenue": 91200, "pbt": 22900, "pat": 18700},
        "previous_quarter": {"revenue": 89400, "pbt": 22100, "pat": 18150},
        "year_ago_quarter": {"revenue": 85500, "pbt": 20600, "pat": 16820}})},
    "s07": {"status": "ok", "kind": "generic", "summary": "'Mega' order (₹10,000–15,000 cr band) for a Middle East hydro project", "importance": 4},
    "s08": {"status": "ok", "kind": "generic", "summary": "CRISIL reaffirms AAA/Stable on NCDs; no change", "importance": 2},
    "s09": {"status": "ok", "kind": "generic", "summary": "USFDA warning letter for Halol plant; supplies from the site at risk", "importance": 5},
    "s10": {"status": "ok", "kind": "generic", "summary": "Interim dividend ₹6.50/share; record date 20 Nov", "importance": 2},
    "s11": {"status": "ok", "kind": "generic", "summary": "Buyback via tender offer approved; size and price to follow", "importance": 4},
    "s12": {"status": "ok", "kind": "generic", "summary": "381 MW wind turbine order from an independent power producer", "importance": 3},
}
for s in store.values():
    if s.get("results"):
        s["summary"] = s["results"]["headline"]
names = {c.symbol: c.name for c in cfg.companies}
sectors = {c.symbol: c.sector for c in cfg.companies}
start = AS_OF - timedelta(days=30)
ann = {"window": {"from": start.isoformat(), "to": AS_OF.isoformat(), "days": 30}, "items": items}
al = {"alerts": alerts}
feed = build_feed(ann, al, store, names, sectors)

# Research sample: real parser + maths on the test fixture page, hand-written model outputs.
sys.path.insert(0, str(ROOT / "tests"))
from test_research import HTML, FakeLLM  # noqa: E402
import finn.pdftext as P  # noqa: E402

P.pages_text = lambda blob, **kw: ["Management commentary"]


class SampleLLM(FakeLLM):
    def json(self, tier, system, user, **kw):
        if tier == "extract":
            if "Nov 2026" in user:
                return {"guidance": [
                    {"metric": "revenue_growth", "quote": "We remain confident of low-teens volume-led growth through the second half",
                     "target_low": 12, "horizon": "H2 FY27", "unit": "%", "page": 5, "speaker": "MD"},
                    {"metric": "ebitda_margin", "quote": "We should operate in a 20 to 24 percent EBITDA band for the year",
                     "target_low": 20, "target_high": 24, "horizon": "FY27", "unit": "%", "page": 7, "speaker": "CFO"}],
                    "tone": "Measured; leaning on rural recovery and lower input costs.",
                    "pushback": ["Rural demand durability", "Pricing versus new entrants"],
                    "segments": [{"name": "Consumer & bazaar", "share_or_growth": "~78% of sales", "page": 3},
                                 {"name": "B2B", "share_or_growth": "~22%, growing faster", "page": 3}]}
            return {"guidance": [
                {"metric": "revenue_growth", "quote": "We expect double-digit growth in the September quarter",
                 "target_low": 10, "horizon": "Q2 FY27", "unit": "%", "page": 4, "speaker": "MD"},
                {"metric": "ebitda_margin", "quote": "Margins should move up to about 22 percent by the second quarter",
                 "target_low": 22, "horizon": "Q2 FY27", "unit": "%", "page": 6, "speaker": "CFO"},
                {"metric": "capex", "quote": "Capex of roughly 400 crore this year, mostly the new adhesives plant",
                 "target_low": 400, "horizon": "FY27", "unit": "₹ cr", "page": 9, "speaker": "CFO"}],
                "tone": "Upbeat on demand; defensive on pricing."}
        return {"promises": [{"id": "G1", "verdict": "too_early", "actual": "H2 FY27 has not started", "note": "Recheck after the Q3 call"},
                             {"id": "G5", "verdict": "too_early", "actual": "H1 capex not split out yet",
                              "note": "Check the H1 cash-flow statement in the Q2 filing"}],
                "narrative_vs_numbers": [
                    {"claim": "Margins expanding on lower input costs", "reality": "OPM flat at 20–21% for nine quarters",
                     "agree": False, "cite": "G4; quarterly opm"},
                    {"claim": "Double-digit growth in Q2", "reality": "Sales +10.0% YoY in Q2 FY27", "agree": True,
                     "cite": "G3; Q2 FY27 sales_yoy"},
                    {"claim": "Working capital under control", "reality": "Debtor days up from 40 to 48 over five years",
                     "agree": False, "cite": "ratios Debtor Days"}],
                "bull": [{"point": "Sales compounding ~8% with steady 20% OPM", "cite": "annual sales, opm"},
                         {"point": "Cash conversion near 1x over three years", "cite": "cfo / pat"},
                         {"point": "Debt down to almost nil", "cite": "borrowings"}],
                "bear": [{"point": "Promised margin step-up has not shown up", "cite": "G4"},
                         {"point": "Receivable days creeping up every year", "cite": "Debtor Days"},
                         {"point": "70x earnings prices in growth it hasn't shown", "cite": "Stock P/E"}],
                "verdict": "Hits the growth it guides to but keeps promising margin expansion that has not arrived; read margin guidance with a discount."}


demo = R.research("ACME", llm=SampleLLM(ROOT / ".cache" / "sample"), n_calls=2,
                  screener=lambda s: R.parse_screener(HTML, "https://www.screener.in/company/ACME/consolidated/") | {"view": "consolidated"},
                  fetch_pdf=lambda url: b"%PDF")
demo["name"] = "Acme Adhesives (sample)"

OUT.mkdir(parents=True, exist_ok=True)
gen = datetime(2026, 11, 13, 17, 30).isoformat()
files = {
    "market.json": {"generated_at": gen, "as_of": AS_OF.isoformat(), "stocks": market, "failed": []},
    "alerts.json": {"generated_at": gen, "as_of": AS_OF.isoformat(), "alerts": alerts,
                    "thresholds": {"global": cfg.alerts_for(""), "overrides": {}}},
    "signals.json": {"generated_at": gen, "as_of": AS_OF.isoformat(), "defaults": cfg.alerts_for(""), "stocks": signals,
                     "overrides": {c.symbol: c.alerts for c in cfg.companies if c.alerts}},
    "feed.json": feed,
    "research/ACME.json": demo,
    "research/index.json": {"ACME": {"name": demo["name"], "as_of": demo["as_of"], "tally": demo["tally"]}},
}
for name, obj in files.items():
    p = OUT / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")
print(f"sample data -> {OUT} · {len(feed['items'])} feed cards {feed['counts']} · {len(alerts)} alerts")
