#!/usr/bin/env python3
"""FINN enrichment pass: LLM reads the filings that matter, then rebuilds feed.json.

Run after `python run_daily.py`.

  python run_enrich.py --dry-run         # show the call plan + token estimate, spend nothing
  python run_enrich.py                   # enrich everything not yet enriched, rebuild feed
  python run_enrich.py --only results    # just the results cards (or management / generic)
  python run_enrich.py --max-calls 40    # hard budget on paid calls this run
  python run_enrich.py --retry-failed    # re-try filings that failed last time
  python run_enrich.py --feed-only       # no LLM; just re-rank with what's already enriched
"""
from __future__ import annotations

import argparse
import json
import logging
import sys

from finn.config import ROOT, load_config
from finn.enrich import Enricher, build_feed
from finn.llm import LLM

OUT = ROOT / "data" / "out"


def read(name: str) -> dict:
    p = OUT / name
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def rebuild_feed(cfg=None) -> dict:
    cfg = cfg or load_config()
    names = {c.symbol: c.name for c in cfg.companies}
    sectors = {c.symbol: c.sector for c in cfg.companies}
    store = read("enrichment.json").get("items", {})
    feed = build_feed(read("announcements.json"), read("alerts.json"), store, names, sectors)
    (OUT / "feed.json").write_text(json.dumps(feed, ensure_ascii=False, indent=1), encoding="utf-8")
    return feed


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="FINN enrichment")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--only", choices=["results", "management", "generic"])
    ap.add_argument("--max-calls", type=int, default=200)
    ap.add_argument("--retry-failed", action="store_true")
    ap.add_argument("--redo", choices=["results", "management", "generic"],
                    help="re-run this kind even if already enriched (e.g. after a prompt fix)")
    ap.add_argument("--feed-only", action="store_true")
    ap.add_argument("-v", "--verbose", action="store_true")
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if a.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)-7s %(message)s", datefmt="%H:%M:%S")

    ann = read("announcements.json")
    if not ann.get("items"):
        print("No data/out/announcements.json yet. Run `python run_daily.py --days 30` first.")
        return 1
    cfg = load_config()

    if not a.feed_only:
        llm = LLM(dry_run=a.dry_run, max_calls=a.max_calls)
        if not a.dry_run and not (llm.available("cheap") or llm.available("extract")):
            print("No GROQ_API_KEY / GEMINI_API_KEY in .env. Building a rules-only feed.")
        else:
            enr = Enricher(llm, OUT / "enrichment.json",
                           sectors={c.symbol: c.sector for c in cfg.companies},
                           names={c.symbol: c.name for c in cfg.companies})
            stats = enr.run(ann["items"], retry_failed=a.retry_failed, only=a.only, redo=a.redo)
            if a.dry_run:
                est = sum(p["est_tokens_in"] for p in llm.planned)
                print(f"\nDRY RUN · {len(llm.planned)} calls planned · ~{est:,} input tokens (estimate)")
                for k, v in sorted(stats.items()):
                    print(f"  {k:<22} {v}")
                return 0
            u = llm.usage.as_dict()
            print(f"\nLLM · {u['calls']} paid calls · {u['cached']} cache hits · "
                  f"{u['tokens_in']:,} in / {u['tokens_out']:,} out tokens")
            for m, d in u["by_model"].items():
                print(f"  {m:<28} {d['calls']} calls")
            for k, v in sorted(stats.items()):
                print(f"  {k:<22} {v}")

    feed = rebuild_feed(cfg)
    c = feed["counts"]
    print(f"\nfeed.json · {len(feed['items'])} cards · {c.get('top', 0)} top · "
          f"{c.get('worth', 0)} worth a look · {c.get('routine', 0)} routine")
    return 0


if __name__ == "__main__":
    sys.exit(main())
