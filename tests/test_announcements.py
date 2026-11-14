from datetime import date

import pytest

from finn import announcements as ann
from finn.config import Company

NSE_ROW = {
    "symbol": "RELIANCE", "desc": "Outcome of Board Meeting", "sm_name": "Reliance Industries Limited",
    "attchmntFile": "https://nsearchives.nseindia.com/corporate/RELIANCE_09112026183015_Outcome.pdf",
    "attchmntText": "Reliance Industries Limited has informed the Exchange that the Board approved "
                    "unaudited financial results for the quarter ended September 30, 2026",
    "an_dt": "09-Nov-2026 18:30:15", "sort_date": "2026-11-09 18:30:15", "seq_id": "104339871",
}
BSE_ROW = {
    "NEWSID": "a1b2c3d4", "SCRIP_CD": 500325, "SLONGNAME": "Reliance Industries Ltd",
    "NEWSSUB": "Reliance Industries Ltd - 500325 - Outcome Of Board Meeting",
    "HEADLINE": "Board approves unaudited financial results for Q2 FY27",
    "CATEGORYNAME": "Board Meeting", "SUBCATNAME": "Outcome of Board Meeting",
    "ATTACHMENTNAME": "abc123.pdf", "NEWS_DT": "2026-11-09T18:31:02.4973333",
}


def test_normalize_nse():
    r = ann.normalize_nse(NSE_ROW, "RELIANCE")
    assert r["source"] == "NSE" and r["filed_at"] == "2026-11-09T18:30:15+05:30"
    assert r["exchange_category"] == "Outcome of Board Meeting" and r["pdf_url"].endswith(".pdf")


def test_normalize_bse_handles_7_digit_fraction_and_builds_pdf_url():
    r = ann.normalize_bse(BSE_ROW, "RELIANCE")
    assert r["filed_at"].startswith("2026-11-09T18:31:02") and r["filed_at"].endswith("+05:30")
    assert r["exchange_category"] == "Board Meeting / Outcome of Board Meeting"
    assert r["pdf_url"] == ann.BSEClient.PDF_BASE + "abc123.pdf"


def test_missing_pdf_is_none_and_ids_are_stable():
    r1 = ann.normalize_nse({**NSE_ROW, "attchmntFile": "-"}, "RELIANCE")
    r2 = ann.normalize_nse({**NSE_ROW, "attchmntFile": "-"}, "RELIANCE")
    assert r1["pdf_url"] is None and r1["id"] == r2["id"]


def test_auto_mode_falls_back_to_bse(monkeypatch):
    def nse_down(self, *a, **k):
        raise ann.FetchError("HTTP 403 (session rejected)")
    monkeypatch.setattr(ann.NSEClient, "announcements", nse_down)
    monkeypatch.setattr(ann.BSEClient, "announcements", lambda self, *a, **k: [BSE_ROW])
    rows, errors = ann.fetch_announcements([Company("RELIANCE", bse_code="500325")],
                                           date(2026, 11, 2), date(2026, 11, 9))
    assert len(rows) == 1 and rows[0]["source"] == "BSE" and rows[0]["category"] == "results"
    assert errors == [{"symbol": "RELIANCE", "source": "NSE", "error": "HTTP 403 (session rejected)",
                       "fatal": False}]


def test_no_bse_code_is_a_fatal_error_when_nse_fails(monkeypatch):
    monkeypatch.setattr(ann.NSEClient, "announcements",
                        lambda self, *a, **k: (_ for _ in ()).throw(ann.FetchError("blocked")))
    rows, errors = ann.fetch_announcements([Company("NEWCO")], date(2026, 11, 2), date(2026, 11, 9))
    assert rows == [] and all(e["fatal"] for e in errors)


def test_nse_html_block_page_raises_fetch_error(monkeypatch):
    class FakeResp:
        status_code = 200
        def raise_for_status(self): pass
        def json(self): raise ValueError("Expecting value")  # NSE served HTML
    client = ann.NSEClient(pause=0)
    monkeypatch.setattr(client, "_warm", lambda: None)
    monkeypatch.setattr(client.session, "get", lambda *a, **k: FakeResp())
    monkeypatch.setattr(ann.time, "sleep", lambda s: None)
    with pytest.raises(ann.FetchError):
        client.announcements("RELIANCE", date(2026, 11, 2), date(2026, 11, 9))


def test_circuit_breaker_stops_hammering_a_blocked_nse(monkeypatch):
    calls = {"nse": 0}
    def nse_down(self, *a, **k):
        calls["nse"] += 1
        raise ann.FetchError("blocked")
    monkeypatch.setattr(ann.NSEClient, "announcements", nse_down)
    monkeypatch.setattr(ann.BSEClient, "announcements", lambda self, *a, **k: [BSE_ROW])
    cos = [Company(f"S{i}", bse_code=str(500000 + i)) for i in range(10)]
    rows, errors = ann.fetch_announcements(cos, date(2026, 11, 2), date(2026, 11, 9))
    assert calls["nse"] == ann.BREAKER and len(rows) == 10
    assert not any(e["fatal"] for e in errors)
