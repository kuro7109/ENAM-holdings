#!/usr/bin/env python3
"""FINN daily refresh: EOD prices -> anomaly alerts, NSE/BSE filings -> classified feed.

Usage
  python run_daily.py                    # prices + last 7 days of filings
  python run_daily.py --days 30          # wider filing window (the digest lets users pick)
  python run_daily.py --only prices      # or: --only announcements
  python run_daily.py --source bse       # nse | bse | auto (NSE first, BSE fallback)
  python run_daily.py --force            # ignore caches, refetch everything
  python run_daily.py --probe RELIANCE   # dump raw NSE/BSE payloads for one symbol (debugging)

Outputs (read by the frontend): data/out/market.json, alerts.json, announcements.json
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

from finn import prices as px
from finn.announcements import BSEClient, FetchError, NSEClient, fetch_announcements
from finn.cache import JsonCache
from finn.classify import is_material
from finn.config import ROOT, Config, load_config
from finn.store import Store

IST = px.IST
OUT = ROOT / "data" / "out"
PRICE_TTL_HOURS = 6       # don't re-hit Yahoo if we already pulled this evening
ANN_CACHE_SECONDS = 1800  # NSE/BSE response cache while iterating
ALERT_HISTORY_SESSIONS = 22  # ~1 month of past alerts for the demo timeline

log = logging.getLogger("finn")


def _now() -> datetime:
    return datetime.now(IST)


def write_json(out_dir: Path, name: str, obj) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    p = out_dir / name
    p.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
    return p


# --------------------------------------------------------------------------- prices
def run_prices(cfg: Config, store: Store, force: bool = False, out_dir: Path = OUT) -> dict:
    now = _now()
    last = store.get_meta("prices_fetched_at")
    fresh = bool(last) and (now - datetime.fromisoformat(last)) < timedelta(hours=PRICE_TTL_HOURS)
    failed: list[str] = []
    if force or not fresh:
        frames, failed = px.fetch_prices(cfg.companies)
        for sym, df in frames.items():
            store.upsert_prices(sym, df)
        if frames:
            store.set_meta("prices_fetched_at", now.isoformat())
    else:
        log.info("prices: using today's cached pull (%s); --force to refetch", last)

    names = {c.symbol: c for c in cfg.companies}
    snapshots, alerts, signals = [], [], {}
    for c in cfg.companies:
        df = store.load_prices(c.symbol)
        if df.empty:
            continue
        a_cfg = cfg.alerts_for(c.symbol)
        sig = px.compute_signals(df, a_cfg)
        signals[c.symbol] = px.signal_history(sig, ALERT_HISTORY_SESSIONS)
        snap = px.snapshot(c.symbol, sig)
        if snap:
            snap.update(name=c.name, sector=c.sector)
            snapshots.append(snap)
        for a in px.detect_alerts(c.symbol, sig, a_cfg, last_n=ALERT_HISTORY_SESSIONS):
            a.update(name=c.name, sector=c.sector)
            alerts.append(a)

    as_of = max((s["date"] for s in snapshots), default=None)
    for s in snapshots:
        s["stale"] = s["date"] < as_of  # no bar for the latest session: suspended, or a data gap

    sev_rank = {"high": 0, "medium": 1}
    alerts.sort(key=lambda a: (a["date"], -sev_rank[a["severity"]]), reverse=True)
    generated = now.isoformat(timespec="seconds")
    write_json(out_dir, "market.json", {"generated_at": generated, "as_of": as_of,
                                        "stocks": snapshots, "failed": failed})
    write_json(out_dir, "alerts.json", {
        "generated_at": generated, "as_of": as_of,
        "thresholds": {"global": cfg.alerts_for(""),
                       "overrides": {s: c.alerts for s, c in names.items() if c.alerts}},
        "alerts": alerts,
    })
    # Raw per-day signals so the app can re-apply *the user's* thresholds instantly, on the phone.
    write_json(out_dir, "signals.json", {"generated_at": generated, "as_of": as_of,
                                         "defaults": cfg.alerts_for(""), "stocks": signals,
                                         "overrides": {s: c.alerts for s, c in names.items() if c.alerts}})
    today = [a for a in alerts if a["date"] == as_of]
    return {"stocks": len(snapshots), "failed": failed, "alerts_today": len(today),
            "alerts_total": len(alerts), "as_of": as_of}


# --------------------------------------------------------------------------- announcements
def run_announcements(cfg: Config, store: Store, days: int = 7, source: str = "auto",
                      force: bool = False, out_dir: Path = OUT) -> dict:
    end = _now().date()
    start = end - timedelta(days=days)
    cache = JsonCache(ttl_seconds=ANN_CACHE_SECONDS, use_cached=not force)
    rows, errors = fetch_announcements(cfg.companies, start, end, source=source, cache=cache)
    new = store.upsert_announcements(rows)

    symbols = [c.symbol for c in cfg.companies]
    items = store.announcements_between(start.isoformat(), (end + timedelta(days=1)).isoformat(), symbols)
    for i in items:
        i["material"] = is_material(i["category"], i["tags"])
    by_cat = Counter(i["category"] for i in items)
    summary = {
        "total": len(items),
        "material": sum(i["material"] for i in items),
        "needs_llm": sum(i["needs_llm"] for i in items),
        "by_category": dict(by_cat.most_common()),
    }
    write_json(out_dir, "announcements.json", {
        "generated_at": _now().isoformat(timespec="seconds"),
        "window": {"from": start.isoformat(), "to": end.isoformat(), "days": days},
        "summary": summary, "items": items, "errors": errors,
    })
    return {**summary, "new": new, "errors": errors}


# --------------------------------------------------------------------------- probe
def probe(symbol: str, cfg: Config) -> None:
    """Print raw payloads so you can confirm field names before trusting the normalisers."""
    end = _now().date()
    start = end - timedelta(days=14)
    c = next((x for x in cfg.companies + cfg.research if x.symbol == symbol.upper()), None)
    for label, fn in (("NSE", lambda: NSEClient().announcements(symbol.upper(), start, end)),
                      ("BSE", (lambda: BSEClient().announcements(c.bse_code, start, end))
                       if c and c.bse_code else None)):
        print(f"\n===== {label} =====")
        if fn is None:
            print("skipped (no bse_code in config)")
            continue
        try:
            rows = fn()
            print(f"{len(rows)} rows in last 14 days")
            if rows:
                print("keys:", sorted(rows[0].keys()))
                print(json.dumps(rows[0], indent=2, ensure_ascii=False)[:1500])
        except FetchError as e:
            print("FAILED:", e)


# --------------------------------------------------------------------------- cli
def _print_errors(errors: list[dict]) -> None:
    """One line per exchange instead of one per stock: when NSE blocks you, it blocks everything."""
    by_src: dict[str, list[dict]] = {}
    for e in errors:
        by_src.setdefault(e["source"], []).append(e)
    for src, errs in by_src.items():
        real = [e for e in errs if not e["error"].startswith("skipped")]
        first = (real[0] if real else errs[0])["error"]
        recovered = len({e["symbol"] for e in errs if not e["fatal"]})
        tail = f" · {recovered} recovered via fallback" if recovered else ""
        print(f"           {src}: {len(errs)} issues{tail} · e.g. {first[:110]}")
    failed = sorted({e["symbol"] for e in errors if e["fatal"]})
    if failed:
        print(f"           no filings for: {', '.join(failed)}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="FINN daily data refresh")
    ap.add_argument("--config", default=None, help="path to portfolio.yaml")
    ap.add_argument("--days", type=int, default=7, help="filing window in days (default 7)")
    ap.add_argument("--only", choices=["prices", "announcements"])
    ap.add_argument("--source", choices=["auto", "nse", "bse"], default="auto")
    ap.add_argument("--force", action="store_true", help="ignore caches")
    ap.add_argument("--probe", metavar="SYMBOL")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)-7s %(message)s", datefmt="%H:%M:%S")
    cfg = load_config(args.config)
    if args.probe:
        probe(args.probe, cfg)
        return 0

    store = Store()
    print(f"\nFINN refresh · {len(cfg.companies)} stocks · {_now():%d %b %Y %H:%M} IST")
    ok = True
    if args.only in (None, "prices"):
        p = run_prices(cfg, store, force=args.force)
        print(f"  prices   {p['stocks']}/{len(cfg.companies)} stocks as of {p['as_of']}"
              f" · {p['alerts_today']} alerts today ({p['alerts_total']} in last month)")
        if p["failed"]:
            print(f"           failed: {', '.join(p['failed'])}")
            ok = False
    if args.only in (None, "announcements"):
        a = run_announcements(cfg, store, days=args.days, source=args.source, force=args.force)
        print(f"  filings  {a['total']} in last {args.days}d · {a['material']} material"
              f" · {a['total'] - a['material']} routine · {a['needs_llm']} need LLM · {a['new']} new")
        _print_errors(a["errors"])
        ok = ok and not any(e["fatal"] for e in a["errors"])
    try:  # re-rank the feed with whatever enrichment already exists (no LLM calls here)
        from run_enrich import rebuild_feed
        f = rebuild_feed(cfg)
        print(f"  feed     {len(f['items'])} cards · {f['counts'].get('top', 0)} top"
              f" · run `python run_enrich.py` to add summaries + results cards")
    except Exception as e:  # the feed is a bonus; never fail the refresh over it
        log.warning("feed rebuild skipped: %s", e)
    print(f"  output   {OUT.relative_to(ROOT)}/\n")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
