#!/usr/bin/env python3
"""Pull-side research for any NSE symbol -> data/research/<SYMBOL>.json

  python run_research.py PIDILITIND                 # one company
  python run_research.py --demo                     # every company under `research:` in portfolio.yaml
  python run_research.py HAVELLS --with-ar          # also read the latest annual report (slower)
  python run_research.py HAVELLS --numbers-only     # no LLM: snapshot / trajectory / balance sheet / cash
  python run_research.py KAYNES --probe             # print what was parsed from screener.in, no LLM
"""
from __future__ import annotations

import argparse
import json
import logging
import sys

from finn.config import load_config
from finn.llm import LLM
from finn.research import ResearchError, compute_numbers, fetch_screener, research, save


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("symbols", nargs="*")
    ap.add_argument("--demo", action="store_true")
    ap.add_argument("--with-ar", action="store_true")
    ap.add_argument("--calls", type=int, default=4, help="how many recent earnings calls to read")
    ap.add_argument("--numbers-only", action="store_true")
    ap.add_argument("--probe", action="store_true")
    ap.add_argument("-v", "--verbose", action="store_true")
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if a.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)-7s %(message)s", datefmt="%H:%M:%S")
    syms = [s.upper() for s in a.symbols]
    if a.demo:
        syms += [c.symbol for c in load_config().research]
    if not syms:
        ap.error("give a symbol or --demo")

    rc = 0
    for sym in syms:
        try:
            if a.probe:
                sc = fetch_screener(sym)
                print(f"\n{sym} · {sc['name']} · {sc['view']}")
                for k, t in sc["tables"].items():
                    print(f"  {k:<14} {len(t['periods']) if t else 0} periods · rows: "
                          f"{', '.join(list(t['rows'])[:8]) if t else '-'}")
                print(f"  ratios         {sc['ratios']}")
                print(f"  transcripts    {len(sc['transcripts'])} · e.g. {sc['transcripts'][:2]}")
                print(f"  annual reports {len(sc['annual_reports'])} · e.g. {sc['annual_reports'][:1]}")
                print(json.dumps(compute_numbers(sc)["snapshot"], indent=1))
                continue
            llm = LLM(max_calls=0 if a.numbers_only else 40)
            n = 0 if a.numbers_only else a.calls
            data = research(sym, llm=llm, n_calls=n, with_ar=a.with_ar and not a.numbers_only,
                            progress=lambda s: print(f"  · {s}"))
            p = save(data)
            c = data["cost"]
            print(f"{sym}: {len(data['promises'])} promises {data['tally']} · {c['calls']} LLM calls · "
                  f"{c['tokens_in']:,} tokens in · {c['seconds']}s -> {p}")
        except ResearchError as e:
            print(f"{sym}: {e}")
            rc = 1
    return rc


if __name__ == "__main__":
    sys.exit(main())
