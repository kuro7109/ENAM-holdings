# FINN backend · Day 1

End-of-day market data and exchange filings for a 15–20 stock NSE portfolio, turned into
three JSON files the mobile frontend reads.

```
Yahoo Finance ──► prices.py ──► signals (move %, volume ratio, σ) ──► alerts.json, market.json
NSE ─┐
     ├──► announcements.py ──► classify.py (rules) ──► announcements.json
BSE ─┘ (fallback)                     │
                                      └── needs_llm=True ──► cheap LLM (Day 2)
```

## Run

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python run_daily.py --probe RELIANCE   # 1. sanity-check the live NSE/BSE payload shape
python run_daily.py                    # 2. full refresh: prices + last 7 days of filings
python -m pytest -q                    # 3. 47 offline tests
```

Flags: `--days 30` (filing window), `--only prices|announcements`, `--source auto|nse|bse`,
`--force` (ignore caches), `-v`. Edit the portfolio and alert thresholds in `config/portfolio.yaml`.

## Outputs (`data/out/`)

| File | What the frontend gets |
|---|---|
| `market.json` | Latest close, daily move, volume ratio, σ, 52-week range and a 30-day sparkline per stock; a `stale` flag when a stock has no bar for the latest session |
| `alerts.json` | Triggered alerts for the last ~month (one card per stock-day, with every trigger that fired, a severity and a plain-English headline), plus the thresholds in force |
| `announcements.json` | Every filing in the window with primary category, secondary categories, tags, `material` and `needs_llm`, plus per-category counts |

## Decisions

**Alerts are configurable, and relative.** Besides the fixed ±X% and k× volume rules, a σ rule
flags moves that are unusual *for that stock* (a 2.5% day in a sleepy bank is news; in a
small-cap it isn't). It only fires when the % rule didn't. Thresholds can be set globally or
per stock. Today's volume is excluded from its own baseline.

**Rules before LLMs.** Exchanges already attach a category and subject to every filing, so
a regex classifier labels most of them for free. Only filings it can't place get
`needs_llm=True`; those are the only ones that will cost a model call.

**Judgment in the classifier.** Board outcomes keep secondary labels (results + dividend).
Scheduling notices, newspaper ads and ESOP allotments are tagged routine so they collapse in
the digest. CEO/CFO/MD/Chair changes are tagged `top_role`. An auditor resigning is tagged
`red_flag` and always surfaces.

**Built not to break the demo.** NSE needs a warmed browser session; the client re-warms on
401/403 or an HTML block page. BSE is a per-symbol fallback. After 3 straight failures an
exchange is skipped for the rest of the run (circuit breaker). Every response is cached on
disk (30 min), prices are fetched at most once per evening, and the frontend reads
precomputed JSON rather than live endpoints.

**Prices are re-pulled in full (1 year, one batched call).** It's ~5k rows, and it means
split/bonus adjustments that Yahoo applies retroactively never leave stale history in the DB.
Today's bar is dropped if the script runs before 15:45 IST, so a half-day volume never gets
compared against full-day averages.

## Known limits

- NSE/BSE field names are undocumented and can change. `--probe` prints the raw keys; the
  normalisers in `announcements.py` are the only place to fix.
- Exchange `subject` lines are sometimes boilerplate. Those filings land in the right
  exchange category but need the PDF text (Day 2) to know *who* or *what*.
- NSE often blocks cloud IPs, so the GitHub Actions refresh may fall back to BSE.
