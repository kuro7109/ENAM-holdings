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

## Interaction model: dashboard first, chat as a layer

A PM's morning is triage, not conversation, so FINN opens on a ranked brief rather than a chat
box. Chat (**Ask**, its own tab, and a button on every screen) is for asking for exactly what you
want instead of hunting for it:
*"Did Kaynes keep its promises?"*, *"What did HAL file this week?"*. Every answer is built only
from FINN's own data (filings, prices, your alerts, research), leads with the number, stays
under ~90 words, and ends with buttons that open the companies it mentions, so chat routes you
back into the dashboard instead of replacing it. It knows which company you're looking at.

- **Grounded retrieval, cheaply:** the app already holds every number, so the client sends only
  the slice the question needs (named companies, recent brief, alerts; ≤24k chars) to
  `web/api/chat.ts`, which adds the rules and calls a Flash-Lite-class model, falling through
  models with separate free quotas. The key never leaves the server.
- **Honest status:** each answer is labelled *AI* or *from saved data*. With no key or no quota, an offline
  answerer handles the common questions (the brief, a company, alerts, comparisons) straight
  from the data, so the feature never dead-ends in a demo.
- **Memory (Supabase):** chat history is saved server-side, and "remember that I care most about
  margins" becomes a note FINN adds to its instructions in later answers; "what do you remember?"
  and "forget …" work too. Tables have row-level security on with no policies, so only the
  server (service-role key, Vercel env) can read or write them (`supabase/schema.sql`). Without
  Supabase, history and notes stay on the device.
- Voice was left out on purpose: dense numbers read better than they sound.

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
| none | rules | classifying 73% of filings (176 of 241), all scoring, every number | Exchanges already label filings; arithmetic doesn't need a model |
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
- **App:** Vercel → import repo → Root Directory `web` (framework: Vite). Every data push redeploys.
  For AI answers in **Ask**, add `GEMINI_API_KEY` (and optionally `GROQ_API_KEY`) under
  Project → Settings → Environment Variables. For memory, run `supabase/schema.sql` in your
  Supabase project and add `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY`. Redeploy after adding.
  Without them, chat answers from saved data and keeps memory on the device.
- **Live research API:** Render → New → Blueprint → this repo (`render.yaml`), add the keys.
- **Daily refresh:** add the three keys as GitHub Actions secrets.

## On real data (30 days to 13 Nov 2026)

241 filings across 18 holdings: 35 ranked top by default, 18 worth a look, 146 folded as routine
(the app's own count can differ: it adds price moves no filing explains and the categories you choose).
Results cards for 12 of the 16 companies that filed (11 with QoQ, 9 with EBITDA; the other 4 link
to the filing). 17 management-change filings parsed into 33 people (who, role, in or out); profile
taken from the filing for 20, web background added for 8 new top-role appointees. 94 one-liners.
Research: Pidilite, Havells, Astral, Kaynes, 14–28 tracked promises each; every promise links to
its transcript page (80 of 80).
Model spend across the logged runs: ~445k input tokens, all on free tiers (₹0).

## Decisions

- **Rules before models.** Exchanges already attach a category and subject to every filing, so
  a regex classifier labels 73% of them for nothing. Only rule misses and material filings get a call.
- **The model reads, Python counts.** For results the model only copies line items from the
  table; QoQ, YoY, margins and EBITDA (= PBT + finance costs + D&A − other income, because
  filings rarely state it) are computed and sanity-checked in code. The same goes for research:
  a guided "10% growth in Q2" is verified against the reported quarter in code; the model
  only judges what arithmetic can't.
- **Primary sources only on the pull side.** Prompts carry only filings, transcripts and the
  annual report. Every promise links to its transcript page; bull/bear points carry a citation
  (prompt-enforced, not machine-verified).
- **The filing first, the web second.** Under SEBI's 13 July 2023 circular on Reg. 30 disclosures,
  an appointment filing must include a brief profile of the appointee, so FINN reads that before
  searching the web (needed for 8 of 33 people).
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
