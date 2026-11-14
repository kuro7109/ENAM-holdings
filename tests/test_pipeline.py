"""End-to-end, fully offline: fake Yahoo + fake exchange feed -> JSON files the frontend reads."""
import json

import run_daily
from finn import announcements as ann
from finn.config import Company, Config
from finn.store import Store
from tests.test_announcements import NSE_ROW
from tests.test_prices import make_frame


def test_full_refresh_writes_frontend_json(tmp_path, monkeypatch):
    cfg = Config(companies=[Company("RELIANCE", name="Reliance", sector="Energy"),
                            Company("DIXON", name="Dixon", sector="EMS", alerts={"price_move_pct": 5.0})],
                 research=[], alerts={})
    frames = {"RELIANCE": make_frame(last_move=0.2), "DIXON": make_frame(seed=3, last_move=7.5, last_volume_mult=3.2)}
    monkeypatch.setattr(run_daily.px, "fetch_prices", lambda companies: (frames, []))
    monkeypatch.setattr(ann.NSEClient, "announcements",
                        lambda self, symbol, s, e: [NSE_ROW] if symbol == "RELIANCE" else [])
    monkeypatch.setattr(run_daily, "_now", lambda: run_daily.datetime(2026, 11, 9, 18, 0, tzinfo=run_daily.IST))
    store = Store(tmp_path / "t.db")
    out = tmp_path / "out"

    p = run_daily.run_prices(cfg, store, out_dir=out)
    a = run_daily.run_announcements(cfg, store, days=7, out_dir=out)
    again = run_daily.run_announcements(cfg, store, days=7, out_dir=out)  # second run: dedupe

    market = json.loads((out / "market.json").read_text())
    alerts = json.loads((out / "alerts.json").read_text())
    feed = json.loads((out / "announcements.json").read_text())

    assert p["stocks"] == 2 and p["alerts_today"] == 1
    assert alerts["alerts"][0]["symbol"] == "DIXON" and alerts["alerts"][0]["severity"] == "high"
    assert alerts["thresholds"]["overrides"] == {"DIXON": {"price_move_pct": 5.0}}
    assert {s["symbol"] for s in market["stocks"]} == {"RELIANCE", "DIXON"}
    assert a["new"] == 1 and again["new"] == 0 and feed["summary"]["total"] == 1
    assert feed["items"][0]["category"] == "results" and feed["items"][0]["material"] is True
