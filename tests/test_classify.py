import pytest

from finn.classify import classify, is_material

MGMT_CAT = "Change in Directors/ Key Managerial Personnel/ Auditor/ Compliance Officer/ Share Transfer Agent"
CONCALL_CAT = "Analysts/Institutional Investor Meet/Con. Call Updates"

CASES = [
    # (exchange category, subject, expected primary)
    ("Integrated Filing- Financial", "Integrated filing for the quarter ended September 30, 2026", "results"),
    ("Outcome of Board Meeting", "Board approves unaudited financial results for Q2 FY27 and declares interim dividend", "results"),
    ("Board Meeting Intimation", "Intimation of board meeting to consider financial results for quarter ended 30 Sep 2026", "results"),
    (MGMT_CAT, "Resignation of Mr. A as Chief Financial Officer and appointment of Mr. B as CFO", "management_change"),
    ("Change in Management", "Appointment of Mr. Rajesh Kumar as Managing Director & CEO", "management_change"),
    (MGMT_CAT, "Appointment of M/s XYZ & Co. as Secretarial Auditor", "unclassified"),
    ("Change in Auditors", "Resignation of Statutory Auditor", "management_change"),
    ("Trading Window-XBRL", "Closure of trading window under SEBI (Prohibition of Insider Trading) Regulations, 2015", "unclassified"),
    (CONCALL_CAT, "Transcript of the earnings conference call for Q2 FY27", "earnings_call"),
    (CONCALL_CAT, "Schedule of analyst / institutional investor meetings", "investor_meetings"),
    ("Credit Rating", "CRISIL reaffirms AA+/Stable rating on bank facilities", "credit_rating"),
    ("Acquisition", "Acquisition of 100% stake in ABC Technologies Pvt Ltd", "M&A"),
    ("Disclosure under SEBI Takeover Regulations", "Disclosure under Regulation 29(2) of SEBI (SAST) Regulations", "insider_trading"),
    ("Disclosure under SEBI Takeover Regulations", "Disclosure of creation of pledge on promoter shares under Regulation 31", "pledging"),
    ("Press Release", "Company bags order worth Rs 1,200 crore from NHAI", "press_release"),
    ("Copy of Newspaper Publication", "Newspaper publication of unaudited financial results", "results"),
    ("Copy of Newspaper Publication", "Newspaper advertisement regarding transfer of shares to IEPF", "unclassified"),
    ("Allotment of Securities", "Allotment of equity shares under ESOP Scheme 2021", "unclassified"),
    ("Shareholders meeting", "Voting results of postal ballot along with scrutinizer's report", "postal_ballot"),
    ("Updates", "Commencement of commercial production at the new Dahej plant", "capex"),
    ("Record Date", "Record date for bonus issue of equity shares in ratio 1:1", "bonus_split"),
    ("Dividend", "Record date for interim dividend of Rs 5 per share", "dividend"),
    ("Updates", "Board approves raising of funds up to Rs 2,000 crore via QIP", "fund_raise"),
    ("Updates", "Receipt of show cause notice from GST authorities with tax demand of Rs 45 crore", "litigation"),
    ("General Updates", "Update on the company's operations in the region", "unclassified"),
]


@pytest.mark.parametrize("cat,subject,expected", CASES)
def test_primary_category(cat, subject, expected):
    assert classify(cat, subject)["category"] == expected


def test_board_outcome_keeps_secondary_labels():
    r = classify("Outcome of Board Meeting", "Board approves financial results for Q2 FY27 and declares interim dividend")
    assert r["category"] == "results" and "dividend" in r["secondary"]


def test_intimations_are_not_material():
    r = classify("Board Meeting Intimation", "Intimation of board meeting to consider financial results")
    assert "intimation" in r["tags"] and not is_material(r["category"], r["tags"])


def test_cfo_change_is_top_role_and_material():
    r = classify(MGMT_CAT, "Resignation of Mr. A as Chief Financial Officer")
    assert "top_role" in r["tags"] and is_material(r["category"], r["tags"])


def test_auditor_resignation_is_a_red_flag():
    r = classify("Change in Auditors", "Resignation of Statutory Auditor")
    assert {"auditor_resignation", "red_flag"} <= set(r["tags"]) and is_material(r["category"], r["tags"])


def test_vague_management_filing_goes_to_llm():
    # NSE subjects are often boilerplate; the exchange category says mgmt change, the PDF says who.
    r = classify("Change in Management", "XYZ Limited has informed the Exchange regarding change in management")
    assert r["category"] == "management_change" and r["needs_llm"]


def test_unknown_goes_to_llm_but_routine_does_not():
    assert classify("General Updates", "Update on the company's operations in the region")["needs_llm"]
    assert not classify(MGMT_CAT, "Appointment of M/s XYZ & Co. as Secretarial Auditor")["needs_llm"]
