#!/usr/bin/env python3
"""Asks for your API keys (input hidden), writes .env, and checks each key works.

    python scripts/setup_keys.py

Press Enter without pasting to keep a key that's already in .env.
"""
from __future__ import annotations

import getpass
import os
import sys
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
ENV = ROOT / ".env"
KEYS = [("GEMINI_API_KEY", "Gemini (aistudio.google.com, starts AIza)"),
        ("GROQ_API_KEY", "Groq (console.groq.com, starts gsk_)"),
        ("TAVILY_API_KEY", "Tavily (app.tavily.com, starts tvly-)")]


def read_env() -> dict:
    out = {}
    if ENV.exists():
        for line in ENV.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.split("=", 1)
                v = v.split(" #")[0].strip().strip('"').strip("'")
                if v:
                    out[k.strip()] = v
    return out


def check_gemini(key: str) -> str:
    r = requests.get("https://generativelanguage.googleapis.com/v1beta/models", params={"key": key}, timeout=20)
    if r.status_code != 200:
        return f"REJECTED ({r.status_code}): {r.text[:120]}"
    names = {m["name"].split("/")[-1] for m in r.json().get("models", [])}
    want = ["gemini-2.5-flash", "gemini-2.5-flash-lite"]
    missing = [m for m in want if m not in names]
    flash = sorted(n for n in names if "flash" in n)[:6]
    return "works" + (f", but {missing} not listed; available flash models: {flash}" if missing else "")


def check_groq(key: str) -> str:
    r = requests.get("https://api.groq.com/openai/v1/models", headers={"Authorization": f"Bearer {key}"}, timeout=20)
    if r.status_code != 200:
        return f"REJECTED ({r.status_code}): {r.text[:120]}"
    names = {m["id"] for m in r.json().get("data", [])}
    want = ["llama-3.1-8b-instant", "llama-3.3-70b-versatile"]
    missing = [m for m in want if m not in names]
    return "works" + (f", but {missing} not listed; available: {sorted(names)[:8]}" if missing else "")


def check_tavily(key: str) -> str:
    return "saved (format looks right)" if key.startswith("tvly-") else "saved, but it doesn't start with tvly-"


def main() -> int:
    current = read_env()
    new = dict(current)
    print("Paste each key and press Enter. Nothing will show while you paste; that's normal.\n")
    for name, label in KEYS:
        have = " (Enter keeps the saved one)" if current.get(name) else ""
        v = getpass.getpass(f"{label}{have}: ").strip().strip('"').strip("'")
        if v:
            new[name] = v
    lines = [f"{k}={new[k]}" for k, _ in KEYS if new.get(k)]
    extras = [f"{k}={v}" for k, v in new.items() if k not in dict(KEYS)]
    ENV.write_text("\n".join(lines + extras) + "\n", encoding="utf-8")
    os.chmod(ENV, 0o600)
    print(f"\nSaved {ENV.name}. Checking keys…")
    checks = {"GEMINI_API_KEY": check_gemini, "GROQ_API_KEY": check_groq, "TAVILY_API_KEY": check_tavily}
    ok = True
    for name, _ in KEYS:
        if not new.get(name):
            print(f"  {name:<15} MISSING")
            ok = False
            continue
        try:
            res = checks[name](new[name])
        except requests.RequestException as e:
            res = f"couldn't reach the service: {e}"
        ok = ok and not res.startswith(("REJECTED", "couldn't"))
        print(f"  {name:<15} {res}")
    print("\nAll set. Next: python run_enrich.py --only results --max-calls 5" if ok
          else "\nFix the lines above, then run this script again.")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
