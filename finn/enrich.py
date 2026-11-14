"""Push-side intelligence: turn the classified filing list into a ranked feed.

  announcements.json + alerts.json  ->  enrichment.json (LLM outputs, keyed by filing id)
                                    ->  feed.json       (what the app renders)

What gets a model call, and which model:
  results filing (one per company per quarter)  extract tier: headline numbers only; QoQ, YoY,
                                                margins and EBITDA are computed here in Python
  management_change                             cheap tier: who / what role / in or out, plus
                                                the profile SEBI requires inside the filing;
                                                web search only if that profile is thin
  other material filings + rule misses          cheap tier: category check + one-line summary
  routine paperwork                             nothing. Collapsed in the app.

Every result is stored by filing id in enrichment.json, so a filing is paid for once, ever.
"""
from __future__ import annotations

import json
import logging
import re
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

from . import pdftext
from .llm import LLM, LLMUnavailable, tavily_search

log = logging.getLogger(__name__)

CATEGORIES = ["results", "M&A", "fund_raise", "management_change", "litigation", "insider_trading",
              "earnings_call", "investor_meetings", "credit_rating", "dividend", "bonus_split", "capex",
              "press_release", "postal_ballot", "agm_egm", "pledging", "unclassified"]
LOW_SIGNAL = {"routine", "intimation", "newspaper_ad"}
LENDER_HINTS = re.compile(r"bank|nbfc|finance|financial|insurance|lending", re.I)

# Base attention weights (0-100). The app lets the user boost or mute categories on top.
WEIGHTS = {
    "results": 80, "M&A": 75, "litigation": 65, "management_change": 55, "fund_raise": 60,
    "pledging": 55, "credit_rating": 45, "capex": 50, "insider_trading": 40, "bonus_split": 40,
    "dividend": 30, "press_release": 30, "earnings_call": 15, "investor_meetings": 8,
    "agm_egm": 8, "postal_ballot": 8, "unclassified": 5,
}
TOP, WORTH = 70, 40  # tier cut-offs


# =========================================================================== results
RESULTS_SYSTEM = """You read Indian listed-company quarterly results filings and copy numbers out of the
results table exactly. You never estimate, never compute, never use outside knowledge.
Return JSON only."""

RESULTS_USER = """Company: {company}
From the results table below, copy the figures for the three QUARTER columns:
  current = the latest quarter, previous_quarter = the quarter just before it,
  year_ago_quarter = the same quarter one year earlier.
Use the CONSOLIDATED statement if present, else standalone. Ignore half-year and full-year columns.

For each quarter give these line items exactly as printed (plain numbers, no commas; negative
for losses; null if the line is not in the table):
  revenue        "Revenue from operations" (for banks/lenders use "Total income")
  other_income   "Other income"
  finance_costs  "Finance costs" / "Interest expense" (lenders: null)
  depreciation   "Depreciation and amortisation expense"
  pbt            "Profit before tax" (after exceptional items)
  pat            "Net profit for the period" / "Profit after tax" (total, before OCI)

JSON shape:
{{"statement": "consolidated|standalone", "unit": "as printed, e.g. ₹ crore / ₹ lakh / ₹ million",
  "is_lender": true|false,
  "labels": {{"current": "e.g. Q2 FY27 (30-Sep-2026)", "previous_quarter": "...", "year_ago_quarter": "..."}},
  "current": {{"revenue": 0, "other_income": 0, "finance_costs": 0, "depreciation": 0, "pbt": 0, "pat": 0}},
  "previous_quarter": {{...same keys...}},
  "year_ago_quarter": {{...same keys...}},
  "found": true}}
If this document has no quarterly results table, return {{"found": false}}.

--- filing text ---
{text}"""

METRICS = ("revenue", "ebitda", "pbt", "pat")


def _num(x):
    try:
        if x is None or x == "":
            return None
        return float(str(x).replace(",", ""))
    except (TypeError, ValueError):
        return None


def growth(cur, base):
    """% change. None when the base is missing, zero or negative (growth off a loss is not a
    number anyone should read)."""
    if cur is None or base is None or base <= 0:
        return None
    return round((cur - base) / base * 100, 1)


def ebitda(q: dict, lender: bool):
    if lender:
        return None
    pbt, fin, dep, oth = (_num(q.get(k)) for k in ("pbt", "finance_costs", "depreciation", "other_income"))
    if pbt is None or dep is None:
        return None
    return round(pbt + (fin or 0) + dep - (oth or 0), 2)


def build_results_card(raw: dict) -> dict | None:
    """LLM gives raw line items; everything derived is computed (and sanity-checked) here."""
    if not raw or not raw.get("found", True) or not raw.get("current"):
        return None
    lender = bool(raw.get("is_lender"))
    quarters = {}
    for key in ("current", "previous_quarter", "year_ago_quarter"):
        q = raw.get(key) or {}
        vals = {k: _num(q.get(k)) for k in ("revenue", "other_income", "finance_costs", "depreciation", "pbt", "pat")}
        vals["ebitda"] = ebitda(vals, lender)
        quarters[key] = vals
    cur, prev, yago = quarters["current"], quarters["previous_quarter"], quarters["year_ago_quarter"]
    if cur.get("revenue") is None and cur.get("pat") is None:
        return None

    rows = []
    for m in METRICS:
        if m == "ebitda" and lender:
            continue
        c = cur.get(m)
        rows.append({
            "metric": {"revenue": "Total income" if lender else "Revenue", "ebitda": "EBITDA",
                       "pbt": "PBT", "pat": "PAT"}[m],
            "key": m, "current": c, "previous_quarter": prev.get(m), "year_ago_quarter": yago.get(m),
            "qoq": growth(c, prev.get(m)), "yoy": growth(c, yago.get(m)),
        })

    def margin(q, k):
        r, v = q.get("revenue"), q.get(k)
        return round(v / r * 100, 1) if r and v is not None and r > 0 else None

    margins = {}
    for k in ("ebitda", "pat"):
        if k == "ebitda" and lender:
            continue
        margins[k] = {"current": margin(cur, k), "previous_quarter": margin(prev, k),
                      "year_ago_quarter": margin(yago, k)}

    checks = []
    if cur.get("pbt") is not None and cur.get("pat") is not None and cur["pat"] > cur["pbt"] * 1.5 + 1:
        checks.append("PAT well above PBT: check for a tax credit or an extraction error")
    if cur.get("revenue") and cur.get("pbt") and cur["pbt"] > cur["revenue"] * 1.2:
        checks.append("PBT above revenue: likely a column mix-up, verify against the filing")

    pat_yoy = next((r["yoy"] for r in rows if r["key"] == "pat"), None)
    rev_yoy = next((r["yoy"] for r in rows if r["key"] == "revenue"), None)
    bits = []
    if rev_yoy is not None:
        bits.append(f"{'Total income' if lender else 'Revenue'} {rev_yoy:+.0f}% YoY")
    if pat_yoy is not None:
        bits.append(f"PAT {pat_yoy:+.0f}% YoY")
    elif cur.get("pat") is not None and (yago.get("pat") or 0) <= 0 < cur["pat"]:
        bits.append("back to profit")
    em = margins.get("ebitda") or {}
    if em.get("current") is not None and em.get("year_ago_quarter") is not None:
        bps = round((em["current"] - em["year_ago_quarter"]) * 100)
        bits.append(f"EBITDA margin {em['current']:.1f}% ({bps:+d} bps)")
    return {
        "statement": raw.get("statement"), "unit": raw.get("unit"), "is_lender": lender,
        "labels": raw.get("labels") or {}, "rows": rows, "margins": margins, "checks": checks,
        "headline": ", ".join(bits),
        "ebitda_note": None if lender else "EBITDA = PBT + finance costs + D&A − other income",
    }


# =========================================================================== management
MGMT_SYSTEM = """You read Indian stock-exchange disclosures about changes in directors and key managerial
personnel. Extract only what the filing states. Return JSON only."""

MGMT_USER = """Company: {company}
Subject: {subject}

List every person whose position changes in this filing.
JSON: {{"people": [{{"name": "...", "role": "e.g. Chief Financial Officer",
  "change": "appointed|resigned|retired|redesignated|ceased|reappointed|other",
  "effective": "date as written or null", "reason": "as stated, <=15 words, or null",
  "profile": "brief profile / experience AS GIVEN IN THE FILING, <=45 words, or null",
  "top_role": true if CEO/CFO/MD/Chair/Whole-time or Executive Director/COO}}],
 "summary": "<=18 words: who, what role, in or out"}}

--- filing text ---
{text}"""

BIO_SYSTEM = """You write a two-sentence professional background of one named person from web search
snippets. Use only the snippets. If they describe different people or are not clearly about this
person at this company, return {"bio": null}. Return JSON only."""

BIO_USER = """Person: {name}, newly {change} as {role} at {company}.
Snippets:
{snippets}

JSON: {{"bio": "<=45 words: current/previous employers, years, education if present" or null,
        "previous_employers": ["..."]}}"""


# =========================================================================== generic
GENERIC_SYSTEM = """You triage Indian stock-exchange filings for a busy portfolio manager. Be terse and
factual; only use the text given. Return JSON only."""

GENERIC_USER = """Company: {company}
Exchange category: {exchange_category}
Subject: {subject}
Rule-based label: {category}

Allowed categories: {categories}
JSON: {{"category": one allowed category,
        "summary": "<=18 words. Lead with the fact that matters; keep numbers (₹, %, dates).",
        "importance": 1-5 (5 = could move the stock; 1 = paperwork),
        "routine": true|false}}

--- first pages of the filing ---
{text}"""


# =========================================================================== orchestration
class Enricher:
    def __init__(self, llm: LLM, store_path: Path, sectors: dict[str, str], names: dict[str, str],
                 fetch=pdftext.fetch_pdf, search=tavily_search):
        self.llm, self.store_path = llm, Path(store_path)
        self.sectors, self.names = sectors, names
        self.fetch, self.search = fetch, search
        self.store = self._load()

    # ---------- persistence ----------
    def _load(self) -> dict:
        if self.store_path.exists():
            try:
                return json.loads(self.store_path.read_text(encoding="utf-8")).get("items", {})
            except json.JSONDecodeError:
                log.warning("enrichment store unreadable, starting fresh")
        return {}

    def save(self) -> None:
        self.store_path.parent.mkdir(parents=True, exist_ok=True)
        self.store_path.write_text(json.dumps({"version": 1, "items": self.store}, ensure_ascii=False,
                                              indent=1), encoding="utf-8")

    def done(self, fid: str, retry_failed: bool) -> bool:
        e = self.store.get(fid)
        return bool(e) and not (retry_failed and e.get("status") == "failed")

    # ---------- text ----------
    def _pages(self, item: dict) -> list[str]:
        return pdftext.pages_text(self.fetch(item.get("pdf_url")))

    # ---------- per kind ----------
    def results(self, item: dict) -> dict:
        pages = self._pages(item)
        text = pdftext.best_pages(pages, pdftext.RESULTS_KEYWORDS, k=3)
        if not text:
            return {"status": "failed", "kind": "results", "error": "no text (scanned or unreachable PDF)"}
        lender_hint = bool(LENDER_HINTS.search(self.sectors.get(item["symbol"], "")))
        raw = self.llm.json("extract", RESULTS_SYSTEM,
                            RESULTS_USER.format(company=item.get("company") or item["symbol"], text=text),
                            max_tokens=1200)
        if raw is None:  # dry run
            return {}
        if lender_hint:
            raw["is_lender"] = True
        card = build_results_card(raw)
        if not card:
            return {"status": "failed", "kind": "results", "error": "no quarterly table found"}
        return {"status": "ok", "kind": "results", "results": card, "summary": card["headline"]}

    def management(self, item: dict) -> dict:
        pages = self._pages(item)
        text = pdftext.head(pages, 6000) or ""
        raw = self.llm.json("cheap", MGMT_SYSTEM,
                            MGMT_USER.format(company=item.get("company") or item["symbol"],
                                             subject=item.get("subject", ""),
                                             text=text or "(PDF text unavailable; use the subject only)"),
                            max_tokens=900)
        if raw is None:
            return {}
        people = [p for p in (raw.get("people") or []) if p.get("name")]
        for p in people:
            if p.get("change") in ("appointed", "redesignated", "reappointed") and p.get("top_role") \
                    and len(p.get("profile") or "") < 80:
                p.update(self._bio(p, item))
        return {"status": "ok" if people else "partial", "kind": "management", "summary": raw.get("summary"),
                "management": {"people": people}}

    def _bio(self, p: dict, item: dict) -> dict:
        company = self.names.get(item["symbol"]) or item.get("company") or item["symbol"]
        try:
            hits = self.search(f'"{p["name"]}" {company} {p.get("role", "")} LinkedIn')
        except Exception as e:
            log.warning("bio search failed for %s: %s", p["name"], e)
            return {}
        if not hits:
            return {}
        snippets = "\n".join(f"- {h['title']} ({h['url']}): {h['content']}" for h in hits)
        try:
            out = self.llm.json("cheap", BIO_SYSTEM, BIO_USER.format(
                name=p["name"], change=p.get("change"), role=p.get("role"), company=company,
                snippets=snippets), max_tokens=300)
        except LLMUnavailable:
            return {}
        if not out or not out.get("bio"):
            return {}
        return {"bio": out["bio"], "previous_employers": out.get("previous_employers") or [],
                "bio_sources": [h["url"] for h in hits[:3]]}

    def generic(self, item: dict) -> dict:
        text = pdftext.head(self._pages(item), 3000)
        raw = self.llm.json("cheap", GENERIC_SYSTEM, GENERIC_USER.format(
            company=item.get("company") or item["symbol"], exchange_category=item.get("exchange_category", ""),
            subject=item.get("subject", ""), category=item.get("category"), categories=", ".join(CATEGORIES),
            text=text or "(no PDF text; judge from the subject)"), max_tokens=250)
        if raw is None:
            return {}
        cat = raw.get("category") if raw.get("category") in CATEGORIES else None
        return {"status": "ok", "kind": "generic", "summary": (raw.get("summary") or "").strip() or None,
                "importance": _clamp(raw.get("importance")), "category": cat, "routine": bool(raw.get("routine"))}

    # ---------- plan + run ----------
    def plan(self, items: list[dict]) -> list[tuple[str, dict]]:
        """Which filings deserve a call, in priority order. Results first (most value per call)."""
        jobs: list[tuple[str, dict]] = []
        for it in pick_results_primaries(items):
            jobs.append(("results", it))
        chosen = {it["id"] for _, it in jobs}
        rest = sorted((i for i in items if i["id"] not in chosen), key=lambda i: -base_score(i))
        for it in rest:
            tags = set(it.get("tags") or [])
            if tags & LOW_SIGNAL and not it.get("needs_llm"):
                continue
            if it["category"] == "results":
                continue  # presentations / press releases ride along with the primary results card
            if it["category"] == "management_change":
                jobs.append(("management", it))
            elif it.get("needs_llm") or it.get("material"):
                jobs.append(("generic", it))
        return jobs

    def run(self, items: list[dict], retry_failed: bool = False, only: str | None = None) -> dict:
        stats = defaultdict(int)
        for kind, it in self.plan(items):
            if only and kind != only:
                continue
            if self.done(it["id"], retry_failed):
                stats["skipped_cached"] += 1
                continue
            if self.llm.dry_run:  # no PDF downloads, no calls: just the plan
                tier = {"results": "extract", "management": "cheap", "generic": "cheap"}[kind]
                est = {"results": 5000, "management": 2000, "generic": 1100}[kind]
                self.llm.planned.append({"tier": tier, "kind": kind, "symbol": it["symbol"], "est_tokens_in": est})
                stats[f"planned_{kind}"] += 1
                continue
            try:
                out = getattr(self, kind)(it)
            except LLMUnavailable as e:
                log.warning("stopping LLM pass: %s", e)
                stats["stopped"] = 1
                break
            except Exception as e:  # never let one weird filing kill the refresh
                log.exception("enrich %s %s failed", kind, it["id"])
                out = {"status": "failed", "kind": kind, "error": str(e)[:200]}
            if not out:  # dry run
                stats[f"planned_{kind}"] += 1
                continue
            out["at"] = datetime.now().isoformat(timespec="seconds")
            self.store[it["id"]] = out
            stats[f"{kind}_{out.get('status')}"] += 1
            log.info("%-10s %-11s %s  %s", it["symbol"], kind, out.get("status"), (out.get("summary") or "")[:70])
            if sum(v for k, v in stats.items() if not k.startswith(("skipped", "planned"))) % 10 == 0:
                self.save()  # checkpoint, so a crash doesn't lose paid-for work
        if not self.llm.dry_run:
            self.save()
        return dict(stats)


def _clamp(x, lo=1, hi=5):
    try:
        return max(lo, min(hi, int(x)))
    except (TypeError, ValueError):
        return None


def _day(iso: str | None) -> date | None:
    try:
        return datetime.fromisoformat(iso).date() if iso else None
    except ValueError:
        return None


RESULTS_MAIN = re.compile(r"financial results?|results for the quarter|\bunaudited\b|\baudited\b", re.I)
RESULTS_SIDE = re.compile(r"press release|presentation|newspaper|earnings release|shareholders?'? letter|"
                          r"investor|monitoring agency|limited review", re.I)


def pick_results_primaries(items: list[dict]) -> list[dict]:
    """One results filing per company: the one most likely to hold the P&L table."""
    best: dict[str, tuple] = {}
    for it in items:
        if it["category"] != "results" or set(it.get("tags") or []) & LOW_SIGNAL:
            continue
        subj = it.get("subject") or ""
        rank = (0 if RESULTS_MAIN.search(subj) and not RESULTS_SIDE.search(subj) else
                1 if not RESULTS_SIDE.search(subj) else 2)
        key = (rank, it.get("filed_at") or "")
        cur = best.get(it["symbol"])
        if cur is None or key[0] < cur[0][0] or (key[0] == cur[0][0] and key[1] > cur[0][1]):
            best[it["symbol"]] = (key, it)
    return [v[1] for v in best.values()]


# =========================================================================== scoring + feed
def base_score(it: dict) -> float:
    tags = set(it.get("tags") or [])
    s = float(WEIGHTS.get(it.get("category"), 5))
    if "top_role" in tags:
        s += 25
    if "red_flag" in tags:
        s += 60
    if tags & LOW_SIGNAL:
        s *= 0.2
    return s


def score(it: dict, enr: dict | None, alert: dict | None) -> tuple[float, list[str]]:
    why: list[str] = []
    tags = set(it.get("tags") or [])
    s = base_score(it)
    if "red_flag" in tags:
        why.append("Red flag")
    if "top_role" in tags:
        why.append("Top-role change")
    if enr:
        if enr.get("routine"):
            s = min(s, 15)
        imp = enr.get("importance")
        if imp:
            s += (imp - 3) * 10
        if enr.get("kind") == "results" and enr.get("status") == "ok":
            yoy = next((r["yoy"] for r in enr["results"]["rows"] if r["key"] == "pat"), None)
            if yoy is not None and abs(yoy) >= 25:
                s += 10
                why.append(f"PAT {yoy:+.0f}% YoY")
    if alert:
        s += 20
        why.append("Stock moved on it" if alert.get("pct_change") is not None else "Unusual trading")
    return round(min(s, 100), 1), why


def _alert_for(it: dict, alerts_by_symbol: dict) -> dict | None:
    """An EOD alert on the filing day, or the next 1-3 days (filings after 15:30 hit the next session)."""
    d = _day(it.get("filed_at"))
    if not d:
        return None
    after_close = (it.get("filed_at") or "")[11:16] >= "15:30"
    lo = d + timedelta(days=1) if after_close else d
    for a in alerts_by_symbol.get(it["symbol"], []):
        ad = date.fromisoformat(a["date"])
        if lo <= ad <= d + timedelta(days=4):
            return {k: a.get(k) for k in ("date", "pct_change", "vol_ratio", "sigma", "headline", "severity")}
    return None


def build_feed(ann: dict, alerts: dict, store: dict, names: dict, sectors: dict) -> dict:
    items = ann.get("items", [])
    by_sym = defaultdict(list)
    for a in alerts.get("alerts", []):
        by_sym[a["symbol"]].append(a)
    for v in by_sym.values():
        v.sort(key=lambda a: a["date"])

    # Cluster: same company + same category + same day -> one card with "related" filings.
    primaries = {i["id"] for i in pick_results_primaries(items)}
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for it in items:
        d = (it.get("filed_at") or "")[:10]
        groups[(it["symbol"], it["category"], d if it["category"] != "results" else "q")].append(it)

    feed = []
    for members in groups.values():
        members.sort(key=lambda i: (i["id"] not in primaries, not store.get(i["id"]), i.get("filed_at") or ""),
                     reverse=False)
        lead = members[0]
        enr = store.get(lead["id"]) or {}
        cat = enr.get("category") or lead["category"]
        alert = _alert_for(lead, by_sym)
        sc, why = score({**lead, "category": cat}, enr, alert)
        out = {
            "id": lead["id"], "symbol": lead["symbol"], "name": names.get(lead["symbol"], lead.get("company")),
            "sector": sectors.get(lead["symbol"], ""), "filed_at": lead.get("filed_at"), "source": lead.get("source"),
            "category": cat, "tags": lead.get("tags") or [], "title": lead.get("subject") or lead.get("exchange_category"),
            "exchange_category": lead.get("exchange_category"), "pdf_url": lead.get("pdf_url"),
            "summary": enr.get("summary") if enr.get("status") in ("ok", "partial") else None,
            "score": sc, "tier": "top" if sc >= TOP else "worth" if sc >= WORTH else "routine", "why": why,
            "enriched": enr.get("status"),
            "related": [{"id": m["id"], "title": m.get("subject"), "pdf_url": m.get("pdf_url"),
                         "filed_at": m.get("filed_at")} for m in members[1:]],
        }
        if enr.get("results"):
            out["results"] = enr["results"]
        if enr.get("management"):
            out["management"] = enr["management"]
        if alert:
            out["alert"] = alert
        feed.append(out)
    feed.sort(key=lambda f: (f["filed_at"] or ""), reverse=True)
    counts = defaultdict(int)
    for f in feed:
        counts[f["tier"]] += 1
    return {"generated_at": datetime.now().isoformat(timespec="seconds"), "window": ann.get("window"),
            "weights": WEIGHTS, "tiers": {"top": TOP, "worth": WORTH}, "counts": dict(counts), "items": feed}
