"""Download a filing / transcript PDF once, extract text, and pick only the pages that matter.

Token discipline: a results filing is often 20-40 pages (auditor's reports, press release,
segment notes). The P&L table is on 1-3 of them. `best_pages` scores pages by keywords so we
send ~3 pages to the model instead of 40.
"""
from __future__ import annotations

import hashlib
import io
import logging
import re
from pathlib import Path

import requests

from .announcements import BROWSER_HEADERS
from .config import ROOT

log = logging.getLogger(__name__)
PDF_DIR = ROOT / ".cache" / "pdf"
MAX_BYTES = 40 * 1024 * 1024


def fetch_pdf(url: str, session=None, timeout: int = 60) -> bytes | None:
    if not url:
        return None
    PDF_DIR.mkdir(parents=True, exist_ok=True)
    path = PDF_DIR / (hashlib.sha1(url.encode()).hexdigest() + ".pdf")
    if path.exists():
        return path.read_bytes()
    s = session or requests.Session()
    headers = {**BROWSER_HEADERS, "Accept": "application/pdf,*/*"}
    if "nseindia" in url:
        headers["Referer"] = "https://www.nseindia.com/"
    elif "bseindia" in url:
        headers["Referer"] = "https://www.bseindia.com/"
    urls = [url]
    if "AttachLive" in url:  # BSE moves older PDFs to AttachHis
        urls.append(url.replace("AttachLive", "AttachHis"))
    for u in urls:
        try:
            r = s.get(u, headers=headers, timeout=timeout)
            if r.status_code != 200 or not r.content.startswith(b"%PDF"):
                continue
            if len(r.content) > MAX_BYTES:
                log.warning("pdf too large (%d MB): %s", len(r.content) // 2**20, u)
                return None
            path.write_bytes(r.content)
            return r.content
        except requests.RequestException as e:
            log.warning("pdf fetch failed %s: %s", u, e)
    return None


def pages_text(blob: bytes | None, max_pages: int = 400) -> list[str]:
    """Text per page. Scanned PDFs come back as empty strings (we then fall back to the
    filing link rather than guess)."""
    if not blob:
        return []
    try:
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(blob))
        out = []
        for i, page in enumerate(reader.pages):
            if i >= max_pages:
                break
            try:
                out.append(_clean(page.extract_text() or ""))
            except Exception:  # one malformed page shouldn't kill the document
                out.append("")
        return out
    except Exception as e:
        log.warning("pdf parse failed: %s", e)
        return []


def _clean(t: str) -> str:
    t = t.replace(" ", " ")
    t = re.sub(r"[ \t]+", " ", t)
    return re.sub(r"\n{3,}", "\n\n", t).strip()


def best_pages(pages: list[str], keywords: list[tuple[str, float]], k: int = 3,
               max_chars: int = 18000) -> str:
    """Top-k pages by weighted keyword hits, returned in document order with page markers."""
    scored = []
    for i, p in enumerate(pages):
        low = p.lower()
        s = sum(w * len(re.findall(kw, low)) for kw, w in keywords)
        if s > 0:
            scored.append((s, i))
    keep = sorted(i for _, i in sorted(scored, reverse=True)[:k])
    chunks, total = [], 0
    for i in keep:
        c = f"[page {i + 1}]\n{pages[i]}"
        if total + len(c) > max_chars:
            c = c[: max(0, max_chars - total)]
        chunks.append(c)
        total += len(c)
        if total >= max_chars:
            break
    return "\n\n".join(chunks)


def head(pages: list[str], max_chars: int = 3500) -> str:
    text = "\n\n".join(f"[page {i + 1}]\n{p}" for i, p in enumerate(pages[:3]) if p)
    return text[:max_chars]


RESULTS_KEYWORDS = [
    (r"profit before tax", 3), (r"revenue from operations", 3), (r"finance costs?", 2),
    (r"depreciation", 2), (r"quarter ended", 2), (r"three months ended", 2), (r"other income", 1),
    (r"consolidated", 1.5), (r"net profit", 1), (r"total income", 1), (r"interest earned", 2),
]
