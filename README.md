# FINN

A mobile-first investing agent for an Indian equity portfolio. It **pushes** what changed and
why it matters, and **pulls** research on any NSE company from primary sources only.

**Try it on a phone:** https://enamholdingsbyroku.vercel.app · Add to Home Screen for the app feel.

## What it does

| Screen | The job |
|---|---|
| **Brief** | Opens with one sentence: *"3 things need you. 38 filings don't."* Covers since you last looked (or 24 h, 3 / 7 / 30 days). Results arrive as a QoQ / YoY table; a CFO change arrives with who the new person is; an auditor resigning is always on top. Routine paperwork folds into one line. **Done** clears an item. |
| **Alerts** | You set what "unusual" means (daily move, volume ×, σ for that stock). As you drag, it shows how many days that setting would have flagged in the last month, so you can tune the noise before committing. You also pick which filing types can reach the top. |
| **Holdings** | 18 stocks, biggest move first, sparkline, volume ×; tap for 52-week range, flagged days and filings. |
| **Research** | Any NSE symbol. The centrepiece is **promised vs delivered**: every guidance statement from the last four earnings calls, checked against reported numbers, each linking to its transcript page. Also narrative vs numbers, trajectory, balance sheet, cash conversion and bull / bear. |

## Architecture

```
                       ┌────────────── run_daily.py (17:00 IST, GitHub Action) ──────────────┐
Yahoo Finance ──► prices.py ──► signals (move %, volume ×, σ) ──► market.json, alerts.json, signals.json
NSE ─┐
     ├─► announcements.py ──► classify.py (rules, free) ──► announcements.json
BSE ─┘                                                    │
                                     run_enrich.py ◄──────┘  only filings that matter cost a call
                                       │  results PDF ──► extract model copies line items ──► Python: QoQ, YoY, EBITDA, margins
                                       │  mgmt change ──► cheap model reads the filing's own profile ──► web search only if thin
                                       │  other material ──► cheap model: one line + importance
                                       └► enrichment.json (cached by filing id) ──► feed.json (ranked, clustered)

screener.in ──► research.py ──► numbers in Python (snapshot, CAGR, D/E, CFO/PAT, working capital)
transcripts ──► extract model: guidance with page refs ──► check_in_code() verifies what arithmetic can
                                                        └► reason model: the rest + narrative vs numbers + bull/bear
                        run_research.py (precomputed demo set)   api/server.py (any ticker, live)

web/ (Vite + React) reads the JSON, re-applies your thresholds on the phone, renders.
```

## Model routing

| Tier | Default model | Used for | Why |
|---|---|---|---|
| none | rules | classifying ~80% of filings, all scoring, every number | Exchanges already label filings; arithmetic doesn't need a model |
| cheap | Groq GPT-OSS 20B (→ Gemini 3.5 Flash-Lite on rate limit) | one-liners, management changes, rule misses | short text, high volume, free and fast |
| extract | Gemini 3.5 Flash → 2.5 Flash (each has its own free quota) | results tables (Gemini only: no answer beats a wrong number), transcripts | long context, must copy numbers exactly |
| reason | Gemini 3.5 Flash (set a Pro model if you have quota) | verdicts the code can't compute, bull / bear | the only step that needs judgment |

All calls go through one OpenAI-compatible client (`finn/llm.py`) with provider fallback, a disk
cache keyed by prompt, a per-run budget (`--max-calls`) and `--dry-run`. Enrichment is stored by
filing id, so each filing is paid for once, ever. Total cost on free tiers: ₹0.

## Run it

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env                      # paste keys right after each '=' (no quotes, no spaces)
# Keys: aistudio.google.com (Gemini), console.groq.com (Groq), app.tavily.com (Tavily).
# Model names can be overridden with FINN_CHEAP_MODEL / FINN_EXTRACT_MODEL / FINN_REASON_MODEL.

python run_daily.py --days 30             # prices, alerts, filings, rules-only feed
python run_enrich.py --dry-run            # see the call plan before spending
python run_enrich.py                      # results cards, people, one-liners -> feed.json
python run_research.py --demo             # precompute research for the companies in portfolio.yaml
python run_research.py HAVELLS --probe    # check what was parsed from screener.in (no LLM)
python -m pytest -q                       # 71 offline tests

cd web && npm install && npm run dev      # app on http://localhost:5173
```

If `data/out` is empty the app falls back to clearly labelled sample data made by the real
pipeline (`scripts/make_sample_data.py`), so the UI can be built offline.

### Deploy
- **App:** Vercel → import repo → Root Directory `web` (framework: Vite). Optional env
  `VITE_API_URL` = the Render URL below. Every data push redeploys.
- **Live research API:** Render → New → Blueprint → this repo (`render.yaml`), add the keys.
- **Daily refresh:** add the three keys as GitHub Actions secrets.

## On real data (30 days to 13 Nov 2026)

241 filings across 18 holdings → ~35 ranked as needing attention, 146 folded as routine.
12 results cards with QoQ/YoY; 17 management changes with who-is-this; 94 one-liners.
Research: Pidilite, Havells, Astral, Kaynes, with 14–28 tracked promises each.
Total model spend for all of it: ~0.5M input tokens on free tiers (₹0).

## Decisions

- **Rules before models.** Exchanges already attach a category and subject to every filing, so
  a regex classifier labels most of them for nothing. Only rule misses and material filings get a call.
- **The model reads, Python counts.** For results the model only copies line items from the
  table; QoQ, YoY, margins and EBITDA (= PBT + finance costs + D&A − other income, because
  filings rarely state it) are computed and sanity-checked in code. The same goes for research:
  a guided "10% growth in Q2" is verified against the reported quarter in code; the model
  only judges what arithmetic can't.
- **Primary sources only on the pull side.** Prompts carry only filings, transcripts and the
  annual report, and every claim must cite a transcript page or a numbers row.
- **The filing first, the web second.** SEBI requires a profile of newly appointed directors
  and KMP inside the disclosure itself, so FINN reads that before searching the web.
- **Relative alerts.** Besides ±X% and k× volume, a σ rule flags moves that are unusual for
  *that* stock. Volatile names keep proportionally looser bars as you move the dial.
- **A move nobody explained is news.** A price/volume alert with no filing behind it surfaces
  as its own item.
- **Built not to break the demo.** NSE with BSE fallback and a circuit breaker; every response
  cached; the app reads precomputed JSON; research for the demo set is precomputed and the live
  API is only for new tickers.

## Left out on purpose

Real push notifications (the brief and alerts model them; web-push is next), voice, intraday
data, per-user portfolios, broker/news data (excluded by design), and the annual report on the
live research path (it's 300 pages; the precomputed demo set uses `--with-ar`).

## Next

Web-push for threshold breaches; per-user weights learned from what they mark Done vs open;
segment-level promise tracking; diffing each new transcript against the last one ("what did
management stop talking about?").
