from finn import research as R
from finn.llm import LLM


def _table(sec, periods, rows):
    th = "".join(f"<th>{p}</th>" for p in periods)
    body = "".join(
        f'<tr><td class="text"><button>{k}&nbsp;<span>+</span></button></td>'
        + "".join(f"<td>{'' if v is None else f'{v:,}'}</td>" for v in vals) + "</tr>"
        for k, vals in rows.items())
    return (f'<section id="{sec}"><table class="data-table"><thead><tr><th></th>{th}</tr></thead>'
            f"<tbody>{body}</tbody></table></section>")


Q = ["Sep 2024", "Dec 2024", "Mar 2025", "Jun 2025", "Sep 2025", "Dec 2025", "Mar 2026", "Jun 2026", "Sep 2026"]
Y = ["Mar 2021", "Mar 2022", "Mar 2023", "Mar 2024", "Mar 2025", "Mar 2026", "TTM"]

HTML = f"""<html><h1>Acme Industries Ltd</h1>
<div class="company-profile"><div class="about"><p>Acme makes adhesives and sealants.</p></div></div>
<ul id="top-ratios">
 <li><span class="name">Market Cap</span><span class="value">₹ <span class="number">1,50,000</span> Cr.</span></li>
 <li><span class="name">Stock P/E</span><span class="value"><span class="number">70.5</span></span></li>
 <li><span class="name">ROCE</span><span class="value"><span class="number">28.1</span> %</span></li>
</ul>
{_table("quarters", Q, {
    "Sales": [1000, 1050, 1100, 1150, 1100, 1160, 1210, 1260, 1210],
    "Operating Profit": [200, 210, 220, 230, 220, 232, 242, 252, 254],
    "OPM %": [20, 20, 20, 20, 20, 20, 20, 20, 21],
    "Net Profit": [150, 155, 160, 165, 160, 170, 175, 180, 184]})}
{_table("profit-loss", Y, {
    "Sales": [3000, 3300, 3700, 4100, 4400, 4630, 4840],
    "OPM %": [19, 19, 20, 20, 20, 20, 20.5],
    "Net Profit": [400, 450, 520, 600, 630, 665, 709]})}
{_table("balance-sheet", Y[:-1], {
    "Equity Capital": [50] * 6, "Reserves": [2000, 2300, 2700, 3100, 3500, 3900],
    "Borrowings": [300, 280, 250, 200, 150, 100]})}
{_table("cash-flow", Y[:-1], {
    "Cash from Operating Activity": [380, 420, 500, 590, 610, 640],
    "Cash from Investing Activity": [-200, -220, -250, -300, -310, -330]})}
{_table("ratios", Y[:-1], {"Debtor Days": [40, 41, 42, 43, 45, 48], "ROCE %": [25, 26, 27, 28, 28, 28]})}
<section id="documents">
 <div class="documents annual-reports"><ul class="list-links">
  <li><a href="https://x/ar2026.pdf">Financial Year 2026<div>from bse</div></a></li></ul></div>
 <div class="documents concalls"><ul class="list-links">
  <li><div>Nov 2026</div><a class="concall-link" href="https://x/t1.pdf" title="Raw Transcript">Transcript</a>
      <a href="https://x/p1.pdf">PPT</a></li>
  <li><div>Aug 2026</div><a class="concall-link" href="https://x/t2.pdf">Transcript</a></li>
 </ul></div>
</section></html>"""


def test_parse_screener_tables_ratios_documents():
    sc = R.parse_screener(HTML, "u")
    assert sc["name"] == "Acme Industries Ltd"
    assert sc["ratios"]["Market Cap"] == 150000 and sc["ratios"]["ROCE"] == 28.1
    assert sc["tables"]["quarters"]["rows"]["Sales"][-1] == 1210  # "+" button stripped from label
    assert [t["month"] for t in sc["transcripts"]] == ["Nov 2026", "Aug 2026"]
    assert sc["annual_reports"][0]["label"] == "Financial Year 2026"


def test_fiscal_quarter_mapping():
    assert R.fy_quarter("Sep 2026") == "Q2 FY27"
    assert R.fy_quarter("Mar 2026") == "Q4 FY26"
    assert R.fy_quarter("Dec 2025") == "Q3 FY26"
    assert R.quarter_discussed("Nov 2026") == "Q2 FY27"
    assert R.quarter_discussed("Feb 2027") == "Q3 FY27"
    assert R.quarter_discussed("May 2026") == "Q4 FY26"


def test_numbers_are_computed_without_a_model():
    n = R.compute_numbers(R.parse_screener(HTML, "u"))
    q = n["trajectory"]["quarterly"]
    assert q[-1]["q"] == "Q2 FY27" and q[-1]["sales_yoy"] == 10.0  # 1210 vs 1100
    assert n["snapshot"]["ttm_sales"] == 4840
    assert n["balance"]["de"] == round(100 / 3950, 2)
    assert n["cash"]["cfo_to_pat_3y"] == round((590 + 610 + 640) / (600 + 630 + 665), 2)
    assert n["trajectory"]["sales_cagr_3y"] == R._cagr(4630, 3700, 3)


def test_promise_checks_in_code():
    n = R.compute_numbers(R.parse_screener(HTML, "u"))
    q, a = n["trajectory"]["quarterly"], n["trajectory"]["annual"]
    hit = R.check_in_code({"metric": "revenue_growth", "target_low": 10, "horizon": "Q2 FY27"}, q, a)
    miss = R.check_in_code({"metric": "revenue_growth", "target_low": 18, "horizon": "Q2 FY27"}, q, a)
    margin = R.check_in_code({"metric": "ebitda_margin", "target_low": 22, "horizon": "Q2 FY27"}, q, a)
    later = R.check_in_code({"metric": "revenue_growth", "target_low": 12, "horizon": "Q4 FY27"}, q, a)
    ytd = R.check_in_code({"metric": "ebitda_margin", "target_low": 20, "horizon": "FY27"}, q, a)
    h1 = R.check_in_code({"metric": "revenue_growth", "target_low": 8, "horizon": "H1 FY27"}, q, a)
    assert ytd["verdict"] == "on_track" and "so far" in ytd["actual"]
    assert h1["verdict"] == "delivered" and h1["actual_value"] == round((1260 + 1210 - 1150 - 1100) / 2250 * 100, 1)
    assert hit["verdict"] == "delivered" and miss["verdict"] == "missed"
    assert margin["verdict"] == "partly"  # 21% vs 22% guided (254/1210 = 21.0%)
    assert later["verdict"] == "too_early"
    assert R.check_in_code({"metric": "capex", "target_low": 500, "horizon": "FY27"}, q, a) is None


class FakeLLM(LLM):
    def __init__(self, tmp):
        super().__init__(cache_dir=tmp)
        self.prompts = []

    def available(self, tier):
        return True

    def json(self, tier, system, user, **kw):
        self.prompts.append((tier, system))
        if tier == "extract":
            return {"guidance": [
                {"metric": "revenue_growth", "quote": "We expect double-digit growth", "target_low": 10,
                 "horizon": "Q2 FY27", "unit": "%", "page": 4},
                {"metric": "capex", "quote": "Capex of 400 crore this year", "target_low": 400,
                 "horizon": "FY27", "unit": "₹ cr", "page": 6}],
                "tone": "Confident", "segments": [{"name": "Adhesives", "share_or_growth": "70%"}]}
        return {"promises": [{"id": "G1", "verdict": "missed", "actual": "wrong"},
                             {"id": "G2", "verdict": "too_early", "actual": "H1 capex 150 cr"}],
                "bull": [{"point": "Margins steady", "cite": "OPM"}], "bear": [{"point": "Debtor days up", "cite": "ratios"}],
                "verdict": "Mostly delivers."}


def test_research_pipeline_end_to_end(tmp_path):
    llm = FakeLLM(tmp_path)
    data = R.research("acme", llm=llm, n_calls=2, screener=lambda s: R.parse_screener(HTML, "u") | {"view": "consolidated"},
                      fetch_pdf=lambda url: None)
    assert data["symbol"] == "ACME" and data["promises"] == []  # PDFs unreadable -> no invented guidance
    assert all(c["status"] == "unreadable" for c in data["calls"])

    import finn.pdftext as P
    orig = P.pages_text
    P.pages_text = lambda blob, **kw: ["Management: we expect double-digit growth"]
    try:
        data = R.research("acme", llm=FakeLLM(tmp_path), n_calls=2,
                          screener=lambda s: R.parse_screener(HTML, "u") | {"view": "consolidated"},
                          fetch_pdf=lambda url: b"%PDF")
    finally:
        P.pages_text = orig
    p = {x["id"]: x for x in data["promises"]}
    assert p["G1"]["verdict"] == "delivered" and p["G1"]["checked_by"] == "code"  # code overrides model
    assert p["G3"]["verdict"] == "delivered"  # second call's copy of the same guidance
    assert p["G2"]["checked_by"] == "model" and p["G2"]["verdict"] == "too_early"  # capex: model judges
    assert "No news" in data["discipline"]
    path = R.save(data, tmp_path / "research")
    assert path.exists() and (tmp_path / "research" / "index.json").exists()


def test_api_serves_cached(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    import api.server as S
    monkeypatch.setattr(S, "RESEARCH_DIR", tmp_path)
    R.save({"symbol": "ACME", "name": "Acme", "as_of": __import__("datetime").date.today().isoformat(),
            "tally": {}}, tmp_path)
    c = TestClient(S.app)
    assert c.get("/api/research/acme").json()["status"] == "ready"
    assert c.get("/api/research/bad sym!").status_code in (400, 404)


def test_absolute_revenue_target_compares_rupees_not_growth():
    n = R.compute_numbers(R.parse_screener(HTML, "u"))
    q, a = n["trajectory"]["quarterly"], n["trajectory"]["annual"]
    c = R.check_in_code({"metric": "revenue_growth", "target_low": 5000, "unit": "₹ cr", "horizon": "FY26"}, q, a)
    assert c["verdict"] == "partly" and "₹4,620 cr of sales vs ₹5,000 cr" in c["actual"]  # Q1..Q4 FY26 = 1150+1100+1160+1210


def test_research_keeps_numbers_when_models_run_out(tmp_path):
    from finn.llm import LLMUnavailable
    import finn.pdftext as P

    class Broke(FakeLLM):
        def json(self, tier, system, user, **kw):
            raise LLMUnavailable("quota")
    orig = P.pages_text
    P.pages_text = lambda blob, **kw: ["We expect double-digit growth"]
    try:
        d = R.research("acme", llm=Broke(tmp_path), n_calls=2,
                       screener=lambda s: R.parse_screener(HTML, "u") | {"view": "consolidated"},
                       fetch_pdf=lambda url: b"%PDF")
    finally:
        P.pages_text = orig
    assert d["snapshot"]["ttm_sales"] == 4840 and d["promises"] == [] and not d["complete"]
    assert [c["status"] for c in d["calls"]] == ["no_model", "no_model"]
