"""First-pass, rule-based announcement classifier (ENAM's categories).

Why rules first: NSE/BSE already attach an exchange category plus a subject line to every
filing, so most filings can be labelled with zero LLM calls. Only the ones the rules can't
place come back with needs_llm=True; those (and only those) go to a cheap model on Day 2.

Output per filing:
  category   primary label (highest-precedence match)
  secondary  other labels that also matched ("results + dividend" board outcomes are common)
  tags       modifiers the priority scorer will use: routine, intimation, newspaper_ad,
             top_role (CEO/CFO/MD/Chair), auditor_resignation, red_flag
  needs_llm  rules weren't confident; send to an LLM (ideally with the PDF text)
"""
from __future__ import annotations

import re
from dataclasses import dataclass


def _rx(*patterns: str) -> tuple[re.Pattern, ...]:
    return tuple(re.compile(p, re.I) for p in patterns)


def _hit(patterns, text: str) -> bool:
    return bool(text) and any(p.search(text) for p in patterns)


# Categories that can move a stock. Drives the quick "N material / M routine" counts;
# Day 2's priority scorer replaces this with weights the user controls.
MATERIAL = {"results", "M&A", "fund_raise", "management_change", "litigation", "insider_trading",
            "credit_rating", "dividend", "bonus_split", "capex", "press_release", "pledging"}
LOW_SIGNAL_TAGS = {"routine", "intimation", "newspaper_ad"}


def is_material(category: str, tags: list[str]) -> bool:
    if "red_flag" in tags:
        return True
    return category in MATERIAL and not (set(tags) & LOW_SIGNAL_TAGS)


# ---------------------------------------------------------------- short-circuit rules
# Always routine, even when they quote a material-sounding regulation
# ("Closure of trading window under SEBI (Prohibition of Insider Trading) Regulations").
HARD_ROUTINE = _rx(
    r"trading window", r"loss of (?:share )?certificates?", r"duplicate (?:share )?certificates?",
    r"74\s*\(\s*5\s*\)", r"\besops?\b", r"\besos\b", r"\besps\b", r"employee stock", r"\bbrsr\b",
    r"business responsibility", r"\besg\b", r"investor (?:grievances?|complaints?)",
    r"compliance certificate", r"certificate under (?:sebi|regulation)", r"shareholding pattern",
    r"secretarial compliance",
)
NEWSPAPER_CAT = _rx(r"news ?paper", r"newspaper publication")
NEWSPAPER_SUBJ = _rx(r"^(?:copy of )?news ?papers? (?:publication|advertisement|advt|cutting|clipping)",
                     r"\bcopy of news ?paper")
# Scheduling notices: they matter for the calendar, not for the feed.
INTIMATION = _rx(
    r"board meeting intimation", r"intimation of (?:the )?(?:board )?meeting",
    r"intimation (?:of|about|regarding) (?:the )?(?:earnings|conference|con\.?)\s?call",
    r"\bto consider\b", r"will be held on", r"is scheduled (?:on|for|to)",
    r"schedule of (?:the )?(?:analyst|investor|earnings|con)", r"prior intimation",
)

# ---------------------------------------------------------------- management change
MGMT_EVENT = _rx(r"change in (?:directors?|management|kmp|key managerial|auditors?)", r"\bappoint",
                 r"\bresign", r"\bcessation\b", r"\bretire", r"re-?designat", r"\bdemise\b",
                 r"step(?:s|ped|ping)? down", r"\belevat")
TOP_ROLE = _rx(r"chief executive", r"\bceo\b", r"chief financial", r"\bcfo\b", r"managing director",
               r"\bmd\b", r"\bm\.\s?d\.", r"chair(?:man|person|woman)", r"whole[- ]?time director",
               r"\bwtd\b", r"(?<!non-)(?<!non )executive director", r"chief operating", r"\bcoo\b")
ROUTINE_ROLE = _rx(r"auditors?", r"company secretary", r"compliance officer", r"share transfer agent",
                   r"registrar", r"scrutini[sz]er", r"nodal officer")
OTHER_SENIOR = _rx(r"\bdirector\b", r"independent directors?", r"additional directors?",
                   r"nominee directors?", r"key managerial", r"\bkmp\b", r"chief [a-z]+ officer",
                   r"senior management", r"\bpresident\b", r"\bcto\b")
_MGMT_CATEGORY = re.compile(r"change in (?:directors?|management|kmp|key managerial)", re.I)


def _management(cat: str, sub: str):
    """Returns (category or None, tags, ambiguous) or None if not a people-change filing."""
    if not _hit(MGMT_EVENT, f"{cat} || {sub}"):
        return None
    s = sub or cat
    tags: list[str] = []
    # Auditor resigning mid-term is one of the loudest red flags in Indian filings.
    if re.search(r"auditor", s, re.I) and re.search(r"resign|cessation", s, re.I):
        tags += ["auditor_resignation", "red_flag"]
    if _hit(TOP_ROLE, s):
        return ("management_change", tags + ["top_role"], False)
    if tags:
        return ("management_change", tags, False)
    if _hit(ROUTINE_ROLE, s):
        return (None, ["routine"], False)
    if _hit(OTHER_SENIOR, s):
        return ("management_change", [], False)
    if _MGMT_CATEGORY.search(cat):
        return ("management_change", [], True)  # exchange says mgmt change, subject too vague
    return None


# ---------------------------------------------------------------- category rules
@dataclass(frozen=True)
class Rule:
    any_: tuple
    not_: tuple = ()
    subject_only: bool = False  # match `any_` on the subject only (exchange category too generic)


RESULTS_ANY = _rx(
    r"financial results?", r"integrated filing\W*financial", r"\bq[1-4]\s*(?:fy\s*)?'?\s*\d{2,4}\b",
    r"\bquarter(?:ly)?\b.{0,40}\bended\b", r"\bun-?audited\b", r"\baudited\b.{0,30}\bresults?\b",
    r"\bresults?\b", r"earnings release", r"shareholders?'? letter",
)

RULES: dict[str, Rule] = {
    "results": Rule(RESULTS_ANY, _rx(
        r"voting results?", r"postal ballot", r"e-?voting", r"scrutini[sz]er", r"transcript",
        r"recording", r"\baudio\b", r"\bvideo\b", r"con(?:ference)?\.?\s?call", r"concall",
        r"earnings call", r"\banalysts?\b", r"investors? meet", r"institutional investor",
        r"general meeting", r"\bagm\b", r"clinical", r"\btrials?\b")),
    "M&A": Rule(_rx(
        r"\bacqui(?:re|res|red|ring|sition|sitions)\b", r"amalgamation", r"\bmerger\b", r"de-?merger",
        r"scheme of arrangement", r"joint venture", r"\bjv\b", r"divest", r"stake (?:sale|purchase)",
        r"(?:sale|disposal|transfer) of (?:(?:its|the|entire|equity) )*(?:stake|business|undertaking)",
        r"sale of (?:shares|stake) (?:in|of) (?:its |the )?(?:subsidiary|associate|jv)", r"slump sale",
        r"incorporation of (?:a )?(?:new )?(?:wholly[- ]owned )?(?:step[- ]down )?subsidiary",
        r"investment in (?:its |the )?(?:wholly[- ]owned )?subsidiar"),
        _rx(r"substantial acquisition", r"takeovers?", r"\bsast\b", r"regulation\s*29", r"\bpledg",
            r"encumbr", r"\biepf\b", r"inter[- ]?se")),
    "fund_raise": Rule(_rx(
        r"\bqip\b", r"qualified institution", r"rights issue", r"preferential (?:issue|allotment|basis)",
        r"buy-?back", r"commercial papers?", r"non[- ]convertible debentures?", r"\bncds?\b",
        r"fund[- ]?rais", r"raising of funds", r"raise (?:of )?funds",
        r"issue of (?:equity shares|debentures|bonds|warrants|securities)", r"\bwarrants\b", r"\bbonds\b",
        r"\bfccbs?\b", r"offer for sale"),
        _rx(r"\bbonus\b", r"\bsplit\b", r"sub-?division", r"\bratings?\b", r"interest (?:payment|due)",
            r"payment of interest", r"redemption")),
    "litigation": Rule(_rx(
        r"litigation", r"\bdisputes?\b", r"regulatory action", r"penalt(?:y|ies)", r"show[- ]cause",
        r"\bscn\b", r"demand (?:order|notice)", r"tax demand", r"\bnclt\b", r"\bnclat\b", r"insolvency",
        r"\bcirp\b", r"winding[- ]up", r"warning letter", r"adjudicat", r"\bfine of\b", r"\bfined\b",
        r"imposed a fine", r"search (?:and|&) seizure", r"\braid\b", r"\bcourt\b", r"tribunal", r"arbitra",
        r"form[- ]?483", r"import alert", r"\boai\b", r"\bsebi\b.{0,20}\border\b", r"\bcbi\b",
        r"enforcement directorate", r"\bfir\b", r"cyber ?(?:attack|security incident)", r"\bfraud",
        r"default(?:ed)? (?:in|on) (?:the )?(?:payment|repayment)")),
    "credit_rating": Rule(_rx(
        r"credit ratings?", r"\bratings?\b", r"\bcrisil\b", r"\bicra\b", r"care ratings?", r"\bcareedge\b",
        r"india ratings", r"\bfitch\b", r"moody", r"\bs&p\b", r"acuite", r"brickwork", r"infomerics")),
    "pledging": Rule(_rx(r"\bpledg", r"encumbr", r"invocation", r"regulation\s*31\b")),
    "insider_trading": Rule(_rx(
        r"insider trading", r"prohibition of insider", r"regulation\s*7\s*\(\s*2\s*\)", r"\bsast\b",
        r"substantial acquisition", r"takeovers?\b", r"regulation\s*29", r"inter[- ]?se transfer",
        r"promoter(?: group)?.{0,40}\b(?:acqui|sale|sold|bought|purchase|creeping)")),
    "capex": Rule(_rx(
        r"\bcapex\b", r"capital expenditure", r"capacity (?:expansion|addition|enhancement)",
        r"expansion of (?:capacity|plant|facility)",
        r"new (?:plant|facility|manufacturing (?:unit|facility|plant)|unit)", r"greenfield", r"brownfield",
        r"commission(?:ing|ed)\b", r"commercial (?:production|operations?)",
        r"setting up (?:of )?(?:a )?(?:new )?(?:plant|facility|unit)", r"\bmtpa\b")),
    "bonus_split": Rule(_rx(r"\bbonus\b", r"sub-?division", r"stock split", r"split of (?:equity )?shares",
                            r"\bsplit\b", r"face value")),
    "dividend": Rule(_rx(r"\bdividends?\b")),
    "earnings_call": Rule(_rx(
        r"con(?:ference)?\.?\s?call", r"concall", r"earnings call", r"\btranscripts?\b",
        r"(?:audio|video) (?:recording|link)", r"recording of", r"\bwebcast\b"), subject_only=True),
    "postal_ballot": Rule(_rx(r"postal ballot")),
    "agm_egm": Rule(_rx(
        r"annual general meeting", r"\bagm\b", r"\begm\b", r"extra-?ordinary general meeting",
        r"general meeting", r"scrutini[sz]er", r"voting results?", r"e-?voting", r"shareholders?'? meeting",
        r"book closure")),
    "investor_meetings": Rule(_rx(
        r"\banalysts?\b", r"institutional investors?", r"investors? (?:meet|meeting|conference|day|call)",
        r"roadshow", r"one[- ]on[- ]one", r"group meetings?", r"fund managers?")),
    "press_release": Rule(_rx(
        r"press release", r"media release", r"\borders? (?:win|received|inflow|book)",
        r"\b(?:bags|wins|won|secures?|secured|receives?|received|bagged) (?:an? |the )?"
        r"(?:new |large |major )?(?:orders?|contracts?|mandates?|work orders?)",
        r"\border\b.{0,40}\b(?:worth|valued|value of)\b", r"letter of (?:award|intent)", r"\bloa\b",
        r"\bloi\b", r"\blaunch", r"partnership", r"collaborat", r"\bmou\b", r"memorandum of understanding",
        r"\bagreements?\b", r"clarification", r"spurt in volume", r"price movement", r"\bawards?\b",
        r"(?:usfda|fda|dcgi|cdsco|ema|regulatory) approval",
        r"approval (?:from|by) (?:the )?(?:usfda|fda|dcgi|cdsco|ema)")),
}

# Order = materiality. The first match becomes the primary category.
PRECEDENCE = ["results", "M&A", "management_change", "fund_raise", "litigation", "credit_rating",
              "pledging", "insider_trading", "capex", "bonus_split", "dividend", "earnings_call",
              "postal_ballot", "agm_egm", "investor_meetings", "press_release"]


def _rule_hit(rule: Rule, text: str, subject: str) -> bool:
    target = subject if rule.subject_only else text
    if not _hit(rule.any_, target):
        return False
    return not _hit(rule.not_, subject or text)  # exclusions judged on the specific subject line


def _out(category: str, secondary: list[str], tags: list[str], needs_llm: bool) -> dict:
    return {"category": category, "secondary": secondary,
            "tags": sorted(set(tags)), "needs_llm": needs_llm}


def classify(exchange_category: str | None, subject: str | None) -> dict:
    cat = " ".join((exchange_category or "").split())
    sub = " ".join((subject or "").split())
    text = f"{cat} || {sub}"
    tags: list[str] = ["intimation"] if _hit(INTIMATION, text) else []

    if _hit(HARD_ROUTINE, text):
        return _out("unclassified", [], tags + ["routine"], False)
    if _hit(NEWSPAPER_CAT, cat) or _hit(NEWSPAPER_SUBJ, sub):
        # ENAM files results newspaper ads under results; they're still routine.
        primary = "results" if _hit(RESULTS_ANY, text) else "unclassified"
        return _out(primary, [], tags + ["newspaper_ad", "routine"], False)

    mgmt = _management(cat, sub)
    matched: list[str] = []
    for name in PRECEDENCE:
        if name == "management_change":
            if mgmt:
                tags += mgmt[1]
                if mgmt[0]:
                    matched.append(name)
            continue
        if _rule_hit(RULES[name], text, sub):
            matched.append(name)

    if matched:
        ambiguous_mgmt = bool(mgmt and mgmt[0] and mgmt[2] and matched[0] == "management_change")
        return _out(matched[0], matched[1:], tags, ambiguous_mgmt)
    return _out("unclassified", [], tags, needs_llm=("routine" not in tags and len(sub) > 15))
