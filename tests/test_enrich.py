import json

import pytest

from finn import enrich as E
from finn.llm import LLM, parse_json


RAW = {
    "statement": "consolidated", "unit": "₹ crore", "is_lender": False,
    "labels": {"current": "Q2 FY27", "previous_quarter": "Q1 FY27", "year_ago_quarter": "Q2 FY26"},
    "current": {"revenue": 1200, "other_income": 20, "finance_costs": 10, "depreciation": 40, "pbt": 200, "pat": 150},
    "previous_quarter": {"revenue": 1000, "other_income": 10, "finance_costs": 10, "depreciation": 40, "pbt": 160, "pat": 120},
    "year_ago_quarter": {"revenue": 1000, "other_income": 10, "finance_costs": 10, "depreciation": 30, "pbt": 100, "pat": 75},
    "found": True,
}


def test_results_card_math_is_done_in_python():
    card = E.build_results_card(RAW)
    rows = {r["key"]: r for r in card["rows"]}
    assert rows["revenue"]["qoq"] == 20.0 and rows["revenue"]["yoy"] == 20.0
    assert rows["pat"]["yoy"] == 100.0
    # EBITDA = PBT + finance + D&A - other income
    assert rows["ebitda"]["current"] == 200 + 10 + 40 - 20
    assert card["margins"]["ebitda"]["current"] == round(230 / 1200 * 100, 1)
    assert "PAT +100% YoY" in card["headline"]
    assert card["checks"] == []


def test_results_card_lender_drops_ebitda():
    card = E.build_results_card({**RAW, "is_lender": True})
    assert [r["key"] for r in card["rows"]] == ["revenue", "pbt", "pat"]
    assert card["rows"][0]["metric"] == "Total income"
    assert card["ebitda_note"] is None


def test_growth_off_a_loss_is_not_a_number():
    assert E.growth(50, -20) is None
    assert E.growth(50, 0) is None
    assert E.growth(None, 10) is None


def test_results_sanity_check_flags_column_mixups():
    bad = json.loads(json.dumps(RAW))
    bad["current"]["pbt"] = 5000
    assert E.build_results_card(bad)["checks"]


def test_results_card_rejects_not_found():
    assert E.build_results_card({"found": False}) is None


def _item(i, sym, cat, subj, tags=(), filed="2026-11-10T16:05:00+05:30", **kw):
    return {"id": i, "symbol": sym, "company": sym, "category": cat, "subject": subj, "tags": list(tags),
            "filed_at": filed, "pdf_url": f"https://x/{i}.pdf", "exchange_category": "", "material": True,
            "needs_llm": False, **kw}


def test_pick_results_primary_prefers_the_pnl_filing():
    items = [_item("a", "INFY", "results", "Press release on results"),
             _item("b", "INFY", "results", "Financial results for the quarter ended 30 Sep 2026"),
             _item("c", "INFY", "results", "Investor presentation")]
    assert [i["id"] for i in E.pick_results_primaries(items)] == ["b"]


def test_routine_scores_low_and_red_flags_surface():
    routine = _item("r", "ITC", "results", "Newspaper ad", tags=["newspaper_ad", "routine"])
    red = _item("x", "ITC", "management_change", "Resignation of statutory auditor",
                tags=["auditor_resignation", "red_flag"])
    assert E.score(routine, None, None)[0] < E.TOP / 2
    s, why = E.score(red, None, None)
    assert s >= E.TOP and "Red flag" in why


def test_feed_links_filing_to_next_session_alert_and_clusters():
    items = [_item("b", "INFY", "results", "Financial results Q2"),
             _item("c", "INFY", "results", "Investor presentation"),
             _item("d", "ITC", "dividend", "Record date", filed="2026-11-09T10:00:00+05:30")]
    alerts = {"alerts": [{"symbol": "INFY", "date": "2026-11-11", "pct_change": 6.2, "vol_ratio": 3.1,
                          "sigma": 3.4, "headline": "+6.2%", "severity": "high"}]}
    store = {"b": {"status": "ok", "kind": "results", "results": E.build_results_card(RAW), "summary": "x"}}
    feed = E.build_feed({"items": items, "window": {}}, alerts, store, {"INFY": "Infosys"}, {})
    infy = next(f for f in feed["items"] if f["symbol"] == "INFY")
    assert infy["id"] == "b" and len(infy["related"]) == 1  # presentation folded in
    assert infy["alert"]["date"] == "2026-11-11"            # filed after close -> next session
    assert infy["tier"] == "top" and infy["results"]["rows"]
    assert len(feed["items"]) == 2


class FakeLLM(LLM):
    def __init__(self, tmp, answers):
        super().__init__(cache_dir=tmp)
        self.answers, self.seen = answers, []

    def json(self, tier, system, user, **kw):
        self.seen.append(tier)
        return self.answers[tier](user)


def test_enricher_routes_tiers_and_persists(tmp_path):
    items = [_item("b", "INFY", "results", "Financial results Q2"),
             _item("m", "TITAN", "management_change", "Appointment of CFO", tags=["top_role"]),
             _item("g", "LT", "press_release", "Order win"),
             _item("z", "LT", "unclassified", "Compliance certificate", tags=["routine"])]
    answers = {
        "extract": lambda u: RAW,
        "cheap": lambda u: ({"people": [{"name": "A Kumar", "role": "CFO", "change": "appointed",
                                         "top_role": True, "profile": None}], "summary": "A Kumar named CFO"}
                            if "position changes" in u else
                            {"bio": "Ex-CFO at X for 8 years.", "previous_employers": ["X"]} if "Snippets" in u else
                            {"category": "press_release", "summary": "Bags ₹2,000 cr order", "importance": 4}),
    }
    llm = FakeLLM(tmp_path / "c", answers)
    page = "Revenue from operations ... Profit before tax ... quarter ended"
    enr = E.Enricher(llm, tmp_path / "enrichment.json", sectors={}, names={},
                     fetch=lambda url: b"%PDF", search=lambda q: [{"title": "t", "url": "u", "content": "c"}])
    enr._pages = lambda it: [page]
    stats = enr.run(items)
    assert llm.seen.count("extract") == 1           # results -> long-context model
    assert "z" not in enr.store                      # routine -> no call at all
    assert enr.store["m"]["management"]["people"][0]["bio"].startswith("Ex-CFO")
    assert enr.store["g"]["summary"] == "Bags ₹2,000 cr order"
    assert stats["results_ok"] == 1
    # second run is free
    llm.seen.clear()
    E.Enricher(llm, tmp_path / "enrichment.json", {}, {}).run(items)
    assert llm.seen == []


def test_parse_json_handles_fences_and_chatter():
    assert parse_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert parse_json('Sure! {"a": 2} hope that helps') == {"a": 2}
    with pytest.raises(Exception):
        parse_json("no json here")


def test_llm_caches_and_falls_back(tmp_path, monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "k1")
    monkeypatch.setenv("GEMINI_API_KEY", "k2")

    class Resp:
        def __init__(self, code, body=None):
            self.status_code, self._b, self.headers = code, body, {}

        def raise_for_status(self):
            if self.status_code >= 400:
                raise RuntimeError(f"HTTP {self.status_code}")

        def json(self):
            return self._b

    calls = []

    class Sess:
        def post(self, url, **kw):
            calls.append(url)
            if "groq" in url:
                return Resp(500)
            return Resp(200, {"choices": [{"message": {"content": '{"ok": true}'}}],
                              "usage": {"prompt_tokens": 10, "completion_tokens": 2}})

    llm = LLM(cache_dir=tmp_path, session=Sess())
    assert llm.json("cheap", "s", "u") == {"ok": True}       # groq fails -> gemini fallback
    n = len(calls)
    assert llm.json("cheap", "s", "u") == {"ok": True}       # groq still fails, gemini answer cached
    assert len(calls) == n + 1 and llm.usage.cached == 1


def test_exchange_summary_is_free_fallback_and_cheap_input(tmp_path):
    es = ("Reliance Industries Limited disclosed that its executives will participate in the Morgan Stanley "
          "Summit in Singapore on November 18 and 19, 2026. The meetings are one-on-one.")
    assert E.first_sentence(es).startswith("Disclosed that its executives will participate")
    it = _item("g", "LT", "press_release", "Order win", exchange_summary="L&T Limited has bagged a large order worth over Rs 5,000 crore for a metro project.")
    feed = E.build_feed({"items": [it]}, {}, {}, {}, {})
    assert feed["items"][0]["summary"].startswith("Bagged a large order")
    seen = []
    llm = FakeLLM(tmp_path / "c", {"cheap": lambda u: seen.append(u) or {"summary": "x", "importance": 3}})
    enr = E.Enricher(llm, tmp_path / "e.json", {}, {}, fetch=lambda u: (_ for _ in ()).throw(AssertionError("no PDF")))
    enr.generic(it)
    assert "exchange's own summary" in seen[0]


def test_missing_year_ago_is_not_back_to_profit_and_one_offs_leave_ebitda():
    raw = json.loads(json.dumps(RAW))
    raw["year_ago_quarter"] = {}
    card = E.build_results_card(raw)
    assert "back to profit" not in card["headline"] and not card["complete"]
    raw = json.loads(json.dumps(RAW))
    raw["current"].update(exceptional=-100, pbt=100)  # a 100 cr one-off loss inside PBT
    card = E.build_results_card(raw)
    assert next(r for r in card["rows"] if r["key"] == "ebitda")["current"] == 100 + 10 + 40 - 20 + 100


def test_results_falls_back_to_next_filing(tmp_path):
    items = [_item("a", "MARUTI", "results", "Financial results for the quarter ended Sep 2026"),
             _item("b", "MARUTI", "results", "Outcome of board meeting - results", filed="2026-11-09T16:00:00+05:30")]
    calls = []
    llm = FakeLLM(tmp_path / "c", {"extract": lambda u: calls.append(u) or ({"found": False} if len(calls) == 1 else RAW)})
    enr = E.Enricher(llm, tmp_path / "e.json", {}, {})
    enr._pages = lambda it: ["Revenue from operations Profit before tax quarter ended"]
    enr.run(items)
    assert enr.store["a"]["status"] == "ok" and enr.store["a"]["source_id"] == "b" and len(calls) == 2


def test_ebitda_prefers_printed_pre_exceptional_and_ignores_wild_one_offs():
    raw = json.loads(json.dumps(RAW))
    raw["current"].update(pbt_pre_exceptional=200, exceptional=12688, pbt=12888)  # sign-confused one-off
    e = next(r for r in E.build_results_card(raw)["rows"] if r["key"] == "ebitda")["current"]
    assert e == 200 + 10 + 40 - 20
    raw["current"].update(pbt_pre_exceptional=None)
    card = E.build_results_card(raw)
    assert next(r for r in card["rows"] if r["key"] == "ebitda")["current"] == 12888 + 10 + 40 - 20
    assert any("unusually large" in c for c in card["checks"])


def test_daily_quota_skips_model_immediately(tmp_path, monkeypatch):
    import finn.llm as L
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    L.EXHAUSTED.clear()
    hits = []

    class R:
        def __init__(self, code, body=None, text=""):
            self.status_code, self._b, self.text, self.headers = code, body, text, {}
        def raise_for_status(self):
            if self.status_code >= 400:
                raise RuntimeError(self.status_code)
        def json(self):
            return self._b

    class S:
        def post(self, url, json=None, **kw):
            hits.append(json["model"])
            if json["model"] == "gemini-2.5-flash":
                return R(429, text='{"error": {"message": "Quota exceeded: GenerateRequestsPerDayPerProjectPerModel-FreeTier"}}')
            return R(200, {"choices": [{"message": {"content": '{"ok": 1}'}}], "usage": {}})

    llm = LLM(cache_dir=tmp_path, session=S())
    assert llm.json("extract", "s", "u1") == {"ok": 1}
    assert llm.json("extract", "s", "u2") == {"ok": 1}
    assert hits == ["gemini-2.5-flash", "gemini-2.5-flash-lite", "gemini-2.5-flash-lite"]  # no waiting, no retry
    L.EXHAUSTED.clear()
