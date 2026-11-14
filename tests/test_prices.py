from datetime import datetime

import numpy as np
import pandas as pd

from finn.config import DEFAULT_ALERTS
from finn.prices import IST, clean, compute_signals, detect_alerts, drop_partial_bar, snapshot


def make_frame(n=90, daily_vol=1.0, seed=7, last_move=None, last_volume_mult=None):
    rng = np.random.default_rng(seed)
    rets = rng.normal(0, daily_vol, n) / 100
    if last_move is not None:
        rets[-1] = last_move / 100
    close = 100 * np.cumprod(1 + rets)
    vol = rng.integers(90_000, 110_000, n).astype(float)
    if last_volume_mult:
        vol[-1] = vol[-21:-1].mean() * last_volume_mult
    idx = pd.bdate_range("2026-06-01", periods=n)
    return pd.DataFrame({"open": close, "high": close, "low": close, "close": close,
                         "adj_close": close, "volume": vol}, index=idx)


def run(df, cfg=DEFAULT_ALERTS):
    return detect_alerts("TEST", compute_signals(df, cfg), cfg)


def test_price_and_volume_spike_is_high_severity():
    alerts = run(make_frame(last_move=6.0, last_volume_mult=3.0))
    assert len(alerts) == 1
    assert {t["type"] for t in alerts[0]["triggers"]} == {"price_move", "volume_spike"}
    assert alerts[0]["severity"] == "high"
    assert "+6.0%" in alerts[0]["headline"] and "3.0x" in alerts[0]["headline"]


def test_quiet_stock_small_move_flags_as_unusual():
    # 2.5% is below the 4% rule, but ~5 sigma for a stock that usually moves 0.5%
    alerts = run(make_frame(daily_vol=0.5, last_move=2.5))
    assert [t["type"] for t in alerts[0]["triggers"]] == ["unusual_for_stock"]


def test_normal_day_is_silent():
    assert run(make_frame(last_move=0.3, last_volume_mult=1.1)) == []


def test_per_stock_override_raises_the_bar():
    cfg = {**DEFAULT_ALERTS, "price_move_pct": 8.0, "sigma_threshold": None}
    assert run(make_frame(last_move=6.0), cfg) == []


def test_volume_baseline_excludes_today():
    sig = compute_signals(make_frame(last_volume_mult=4.0), DEFAULT_ALERTS)
    assert abs(sig["vol_ratio"].iloc[-1] - 4.0) < 1e-9  # would be ~3.3 if today polluted its own average


def test_partial_bar_dropped_only_during_market_hours():
    df = make_frame(n=30)
    d = df.index[-1]
    assert len(drop_partial_bar(df, datetime(d.year, d.month, d.day, 11, 0, tzinfo=IST))) == 29
    assert len(drop_partial_bar(df, datetime(d.year, d.month, d.day, 16, 30, tzinfo=IST))) == 30


def test_clean_handles_yahoo_shape():
    raw = make_frame(n=10).rename(columns={"open": "Open", "high": "High", "low": "Low", "close": "Close",
                                            "adj_close": "Adj Close", "volume": "Volume"})
    raw.index = raw.index.tz_localize("Asia/Kolkata")          # Ticker.history() is tz-aware
    raw.iloc[3, raw.columns.get_loc("Volume")] = 0              # holiday placeholder row
    out = clean(raw, now=datetime(2030, 1, 1, tzinfo=IST))
    assert list(out.columns) == ["open", "high", "low", "close", "adj_close", "volume"]
    assert out.index.tz is None and len(out) == 9


def test_snapshot_fields():
    s = snapshot("TEST", compute_signals(make_frame(), DEFAULT_ALERTS))
    assert len(s["spark"]) == 30 and s["pct_from_52w_high"] <= 0
