# Submission kit

## Morning checklist (about 20 minutes)

1. **Deploy the app on Vercel** (2 min). vercel.com → *Add New…* → *Project* → import
   `kuro7109/ENAM-holdings` → **Root Directory: `web`** (click *Edit*) → Framework: **Vite** → *Deploy*.
   Copy the `https://….vercel.app` link and open it on your phone.
2. **Put the link in the README.** Replace `https://enamholdingsbyroku.vercel.app` near the top of `README.md`
   (GitHub → README → pencil icon → *Commit changes*).
4. **Share the build history.** Open this Claude session, then *Share* → copy the link.
   Do the same for any other AI chats you used.
5. **Optional: daily refresh.** GitHub repo → *Settings* → *Secrets and variables* → *Actions* →
   add `GEMINI_API_KEY`, `GROQ_API_KEY`, `TAVILY_API_KEY`.
6. **Send the email below** to assessment@enam.com, subject **IIT Delhi – AI Engineer - 2027**.

---

## Email

**To:** assessment@enam.com
**Subject:** IIT Delhi – AI Engineer - 2027

Hello ENAM team,

Here is my submission for the FINN build challenge.

- **App (open on a phone):** https://enamholdingsbyroku.vercel.app
- **Repository:** https://github.com/kuro7109/ENAM-holdings
- **AI build history:** <Claude session share link> <any other chat links>

**A 60-second tour:** open the app on a phone and start on **Brief** (what needs you today, with
results and management changes already read). Then **Research → KAYNES**: management promised
₹4,100 cr of FY26 revenue and delivered ₹3,626 cr, promised 85 working-capital days and reached 122,
and promised positive operating cash flow and got −₹600 cr. Each claim links to its transcript page.

**One thing to know upfront:** the research engine works on any NSE symbol, but the deployed app
serves four precomputed companies (Pidilite, Havells, Astral, Kaynes). NSE and screener.in block
cloud servers, so I didn't host the live research API. Any other ticker runs from the repo in
about a minute: `python run_research.py SYMBOL`.

**What I built**

Interaction model, in one line: the dashboard leads and chat is a layer on top. The app opens on a ranked brief, because a PM's morning is triage. **Ask FINN** answers the question the screens didn't anticipate, using only FINN's own data, and routes you back into the right screen.


FINN is a mobile-first triage tool for an 18-stock Indian portfolio, with two modes:

- **Brief (push).** It opens with one sentence, e.g. *"2 things need you. 12 filings don't."* By default it covers the time since you last looked or the last 24 hours, and you can pick 3, 7 or 30 days. On a quiet day it widens itself and says so instead of showing an empty screen.
  - Quarterly results arrive as a Revenue / EBITDA / PBT / PAT table, QoQ and YoY.
  - A management change arrives with who the person is: first the brief profile SEBI's July 2023 disclosure circular requires inside an appointment filing, then a web search only if that profile is thin (8 of 33 people).
  - Red flags, such as an auditor resigning, always surface. Routine paperwork folds into one line. **Done** clears an item.
  - Over the last 30 days: 241 filings; 35 ranked top by default and 146 folded as routine.
- **Alerts.** You set what "unusual" means: daily move %, volume × its 20-day average, and a σ rule (a move that's unusual *for that stock*). As you drag a dial, the app shows how many days that setting would have flagged in the last month, so you can tune the noise before committing. A price or volume move that no filing explains surfaces as its own item.
- **Research (pull), any NSE ticker.** The centrepiece is *promised vs delivered*. Every forward statement management made on the last four earnings calls is pulled with its transcript page. Each one is then checked against the reported quarters (delivered / on track / behind / missed), or against what management itself reported on later calls. It also covers narrative vs numbers, trajectory, balance sheet, cash conversion, and a cited bull / bear case. Demo set: Pidilite, Havells, Astral, Kaynes (16–28 promises each).

**Key decisions and trade-offs**

- **Rules before models.** Exchanges already label filings, so a regex classifier handles 73% of them (176 of 241) for free. Only rule misses and material filings cost a model call. NSE now attaches its own short plain-English summary to each filing; I use its first sentence as a free fallback and the summary as cheap model input instead of the PDF.
- **The model reads, Python counts.** For results, the model only copies line items from the table. QoQ, YoY, margins and EBITDA are computed in code, with one-offs stripped out and sanity checks. On the research side, a promise like "10% growth in Q2" is verified against the reported quarter in code; the model only judges what arithmetic can't.
- **No answer beats a wrong number.** When a fallback model misread a results table, I routed results cards to Gemini only. If no reliable model is available, the card says "Open filing" rather than guessing.
- **Cheap routing.** Groq GPT-OSS 20B handles bulk one-liners. Gemini Flash handles long documents (results tables, transcripts), with a chain of models that each have their own free quota, plus provider fallback. Everything is cached per filing, so nothing is paid for twice. A full month of enrichment plus four research reports came to about 445k input tokens across the logged runs, all on free tiers: ₹0.
- **Primary sources only for research.** Only filings, transcripts and screener.in's standardised financials go into the prompts. Every promise links to its transcript page; bull and bear points each carry a citation.
- **Built not to break the demo.** NSE with BSE fallback and a circuit breaker; on-disk caches; the app reads precomputed JSON, so it loads instantly; demo research is precomputed.

**What I left out on purpose**

Real push notifications (the Brief and Alerts model them), voice (dense numbers read better than they sound), intraday data, per-user portfolios, and news or broker data (excluded by design). A hosted live research API (the FastAPI service and `render.yaml` are in the repo, not deployed).

**Where I'd take it next**

Web push for threshold breaches; learning each user's weights from what they mark Done versus open; diffing each new transcript against the last ("what did management stop talking about?"); and segment-level promise tracking.

Thank you,
Anshika
IIT Delhi
