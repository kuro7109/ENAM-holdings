"""NSE / BSE corporate-announcement fetchers -> one normalised, classified schema.

Default source is "auto": NSE first, BSE as a per-symbol fallback. We deliberately don't
merge both exchanges. Companies file the same document on both, and fuzzy cross-exchange
de-duplication is a rabbit hole that buys the investor nothing.
"""
from __future__ import annotations

import hashlib
import logging
import time
from datetime import date, datetime
from zoneinfo import ZoneInfo

import requests

from .cache import JsonCache
from .classify import classify
from .config import Company

log = logging.getLogger(__name__)
IST = ZoneInfo("Asia/Kolkata")

BROWSER_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate",
    "Connection": "keep-alive",
}


class FetchError(RuntimeError):
    pass


# --------------------------------------------------------------------------- NSE
class NSEClient:
    """NSE's JSON API sits behind bot protection: it wants browser headers plus the cookies
    the HTML pages set. So we warm a session first and re-warm whenever we get a 401/403
    or an HTML block page instead of JSON."""

    BASE = "https://www.nseindia.com"
    API = BASE + "/api/corporate-announcements"
    REFERER = BASE + "/companies-listing/corporate-filings-announcements"

    def __init__(self, cache: JsonCache | None = None, pause: float = 0.7, timeout: int = 20):
        self.cache, self.pause, self.timeout = cache, pause, timeout
        self.session = requests.Session()
        self.session.headers.update({**BROWSER_HEADERS, "Referer": self.REFERER})
        self._warm_ok = False

    def _warm(self) -> None:
        for url in (self.BASE, self.REFERER):
            self.session.get(url, timeout=self.timeout,
                             headers={"Accept": "text/html,application/xhtml+xml,*/*;q=0.8"})
        self._warm_ok = True

    def announcements(self, symbol: str, start: date, end: date) -> list[dict]:
        params = {"index": "equities", "symbol": symbol,
                  "from_date": start.strftime("%d-%m-%Y"), "to_date": end.strftime("%d-%m-%Y")}
        if self.cache:
            hit = self.cache.get(self.API, params)
            if hit is not None:
                return hit
        data = self._get_json(params)
        rows = data if isinstance(data, list) else (data.get("data") or [])
        if self.cache:
            self.cache.set(self.API, params, rows)
        return rows

    def _get_json(self, params: dict, retries: int = 3):
        last: Exception | None = None
        for attempt in range(retries):
            try:
                if not self._warm_ok:
                    self._warm()
                r = self.session.get(self.API, params=params, timeout=self.timeout)
                if r.status_code in (401, 403):
                    raise FetchError(f"HTTP {r.status_code} (session rejected)")
                r.raise_for_status()
                data = r.json()  # ValueError if NSE served an HTML block page
                time.sleep(self.pause)
                return data
            except (requests.RequestException, ValueError, FetchError) as e:
                last = e
                self._warm_ok = False
                time.sleep(1.5 * (attempt + 1))
        raise FetchError(f"NSE {params.get('symbol')}: {last}")


# --------------------------------------------------------------------------- BSE
class BSEClient:
    """BSE keys filings by numeric scrip code (e.g. 500325), not the NSE symbol."""

    API = "https://api.bseindia.com/BseIndiaAPI/api/AnnSubCategoryGetData/w"
    # Recent PDFs live under AttachLive; older ones move to AttachHis (swap if a link 404s).
    PDF_BASE = "https://www.bseindia.com/xml-data/corpfiling/AttachLive/"

    def __init__(self, cache: JsonCache | None = None, pause: float = 0.5,
                 timeout: int = 20, max_pages: int = 20):
        self.cache, self.pause, self.timeout, self.max_pages = cache, pause, timeout, max_pages
        self.session = requests.Session()
        self.session.headers.update({**BROWSER_HEADERS, "Referer": "https://www.bseindia.com/",
                                     "Origin": "https://www.bseindia.com"})

    def announcements(self, scrip_code: str, start: date, end: date) -> list[dict]:
        rows: list[dict] = []
        for page in range(1, self.max_pages + 1):
            params = {"pageno": page, "strCat": "-1", "strPrevDate": start.strftime("%Y%m%d"),
                      "strScrip": str(scrip_code), "strSearch": "P", "strToDate": end.strftime("%Y%m%d"),
                      "strType": "C", "subcategory": "-1"}
            data = self._get_json(params)
            table = data.get("Table") or []
            rows.extend(table)
            total = int(((data.get("Table1") or [{}])[0] or {}).get("ROWCNT") or 0)
            if not table or len(rows) >= total:
                break
        return rows

    def _get_json(self, params: dict, retries: int = 3) -> dict:
        if self.cache:
            hit = self.cache.get(self.API, params)
            if hit is not None:
                return hit
        last: Exception | None = None
        for attempt in range(retries):
            try:
                r = self.session.get(self.API, params=params, timeout=self.timeout)
                r.raise_for_status()
                data = r.json()
                if not isinstance(data, dict):
                    raise ValueError("unexpected BSE payload")
                if self.cache:
                    self.cache.set(self.API, params, data)
                time.sleep(self.pause)
                return data
            except (requests.RequestException, ValueError) as e:
                last = e
                time.sleep(1.5 * (attempt + 1))
        raise FetchError(f"BSE {params.get('strScrip')}: {last}")


# --------------------------------------------------------------------------- normalise
_DT_FORMATS = ("%Y-%m-%d %H:%M:%S", "%d-%b-%Y %H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f",
               "%Y-%m-%dT%H:%M:%S", "%d-%m-%Y %H:%M:%S", "%d-%b-%Y", "%Y-%m-%d")


def parse_dt(value) -> datetime | None:
    if not value:
        return None
    s = str(value).strip()
    if "T" in s and "." in s:  # BSE sometimes sends 7-digit fractions; %f takes max 6
        head, frac = s.split(".", 1)
        s = f"{head}.{frac[:6]}"
    for fmt in _DT_FORMATS:
        try:
            return datetime.strptime(s, fmt).replace(tzinfo=IST)
        except ValueError:
            continue
    return None


def _url(u) -> str | None:
    u = str(u or "").strip()
    return u if u.startswith("http") else None


def _id(source: str, native) -> str:
    return hashlib.sha1(f"{source}|{native}".encode()).hexdigest()[:16]


def _squash(s) -> str:
    return " ".join(str(s or "").split())


def normalize_nse(row: dict, symbol: str) -> dict:
    filed = parse_dt(row.get("sort_date")) or parse_dt(row.get("an_dt"))
    category = _squash(row.get("desc"))
    pdf = _url(row.get("attchmntFile"))
    native = row.get("seq_id") or f"{symbol}|{row.get('an_dt')}|{category}|{pdf}"
    return {
        "id": _id("NSE", native),
        "symbol": symbol,
        "company": _squash(row.get("sm_name")) or symbol,
        "source": "NSE",
        "filed_at": filed.isoformat() if filed else None,
        "exchange_category": category,
        "subject": _squash(row.get("attchmntText")),
        "pdf_url": pdf,
        # NSE's own plain-English summary of the filing: a free one-liner source, and much
        # cheaper model input than the PDF.
        "exchange_summary": _squash(row.get("voiceSummary")) or None,
    }


def normalize_bse(row: dict, symbol: str) -> dict:
    filed = parse_dt(row.get("NEWS_DT")) or parse_dt(row.get("DT_TM"))
    parts = [_squash(row.get(k)) for k in ("CATEGORYNAME", "SUBCATNAME")]
    category = " / ".join(p for p in parts if p and p != "-")
    subject = _squash(row.get("HEADLINE")) or _squash(row.get("NEWSSUB"))
    att = _squash(row.get("ATTACHMENTNAME"))
    native = row.get("NEWSID") or f"{symbol}|{row.get('NEWS_DT')}|{subject}"
    return {
        "id": _id("BSE", native),
        "symbol": symbol,
        "company": _squash(row.get("SLONGNAME")) or symbol,
        "source": "BSE",
        "filed_at": filed.isoformat() if filed else None,
        "exchange_category": category,
        "subject": subject,
        "pdf_url": BSEClient.PDF_BASE + att if att else None,
        "exchange_summary": None,
    }


# --------------------------------------------------------------------------- orchestrate
BREAKER = 3  # after this many straight failures from one exchange (blocked IP), stop retrying it


def fetch_announcements(companies: list[Company], start: date, end: date,
                        source: str = "auto", cache: JsonCache | None = None):
    """Returns (classified rows, errors). Never raises for a single bad symbol:
    one blocked request shouldn't take the whole digest down."""
    clients = {}
    if source in ("nse", "auto"):
        clients["NSE"] = NSEClient(cache)
    if source in ("bse", "auto"):
        clients["BSE"] = BSEClient(cache)
    streak = {name: 0 for name in clients}  # consecutive failures per exchange
    fetched_at = datetime.now(IST).isoformat(timespec="seconds")
    rows: list[dict] = []
    errors: list[dict] = []

    for c in companies:
        got: list[dict] | None = None
        sym_errors: list[dict] = []
        for name, client in clients.items():
            if got is not None:
                break
            if name == "BSE" and not c.bse_code:
                sym_errors.append({"symbol": c.symbol, "source": name, "error": "no bse_code in config"})
                continue
            if streak[name] >= BREAKER:
                sym_errors.append({"symbol": c.symbol, "source": name, "error": "skipped (circuit open)"})
                continue
            try:
                if name == "NSE":
                    got = [normalize_nse(r, c.symbol) for r in client.announcements(c.symbol, start, end)]
                else:
                    got = [normalize_bse(r, c.symbol) for r in client.announcements(c.bse_code, start, end)]
                streak[name] = 0
            except FetchError as e:
                streak[name] += 1
                sym_errors.append({"symbol": c.symbol, "source": name, "error": str(e)})
                if streak[name] == BREAKER:
                    log.warning("%s failed %d times in a row; skipping it for the rest of this run",
                                name, BREAKER)
        for e in sym_errors:
            e["fatal"] = got is None  # False = NSE failed but the BSE fallback covered it
        errors += sym_errors
        for r in got or []:
            r["fetched_at"] = fetched_at
            r.update(classify(r["exchange_category"], r["subject"]))
            rows.append(r)
        log.info("%-12s %s", c.symbol, f"{len(got)} filings" if got is not None else "FAILED")
    return rows, errors
