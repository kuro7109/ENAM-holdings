"""EOD prices (Yahoo Finance) -> per-stock signals -> threshold alerts.

Three signals per stock-day:
  pct_change  daily move on adjusted close
  vol_ratio   volume / trailing N-session average (today excluded from its own baseline)
  sigma       pct_change / std-dev of that stock's own recent daily moves

Why sigma: a fixed +/-X% rule treats every stock the same. A 2.5% day in a sleepy
large-cap bank is news; a 2.5% day in a volatile small-cap is Tuesday. sigma catches
the first without spamming the second. It only fires when the % rule didn't already.
"""
from __future__ import annotations

import logging
import math
import time as _time
from datetime import datetime, time
from zoneinfo import ZoneInfo

import pandas as pd

from .config import Company
from .store import PRICE_COLS

log = logging.getLogger(__name__)
IST = ZoneInfo("Asia/Kolkata")
EOD_READY = time(15, 45)  # NSE closes 15:30 IST; give Yahoo a few minutes to settle the bar


# --------------------------------------------------------------------------- fetch
def fetch_prices(companies: list[Company], period: str = "1y", retries: int = 3):
    """One batched Yahoo call for the whole portfolio, per-ticker fallback for any gaps.

    We re-download a full year every run instead of appending increments. It's ~5k rows
    (trivial), and it means split/bonus adjustments Yahoo applies retroactively never
    leave a stale, unadjusted history in our DB.
    Returns ({symbol: DataFrame}, [failed symbols]).
    """
    import yfinance as yf  # imported lazily so tests run without it

    tickers = [c.yf_ticker for c in companies]
    raw = None
    for attempt in range(retries):
        try:
            raw = yf.download(tickers, period=period, interval="1d", group_by="ticker",
                              auto_adjust=False, progress=False, threads=True)
            break
        except Exception as e:  # yfinance raises a zoo of exception types
            log.warning("yfinance batch attempt %d failed: %s", attempt + 1, e)
            _time.sleep(2 * (attempt + 1))

    frames, failed = {}, []
    for c in companies:
        df = _extract(raw, c.yf_ticker)
        if df is None or df.dropna(how="all").empty:
            df = _single(yf, c.yf_ticker, period)
        try:
            df = clean(df) if df is not None else None
        except ValueError as e:
            log.warning("%s: %s", c.symbol, e)
            df = None
        if df is None or df.empty:
            failed.append(c.symbol)
            continue
        frames[c.symbol] = df
    return frames, failed


def _extract(raw: pd.DataFrame | None, ticker: str) -> pd.DataFrame | None:
    """yf.download's column layout differs by version and ticker count; handle all of them."""
    if raw is None or raw.empty:
        return None
    if isinstance(raw.columns, pd.MultiIndex):
        for level in range(raw.columns.nlevels):
            if ticker in raw.columns.get_level_values(level):
                return raw.xs(ticker, axis=1, level=level).copy()
        return None
    return raw.copy()


def _single(yf, ticker: str, period: str) -> pd.DataFrame | None:
    try:
        return yf.Ticker(ticker).history(period=period, interval="1d", auto_adjust=False)
    except Exception as e:
        log.warning("yfinance single fetch failed for %s: %s", ticker, e)
        return None


def clean(df: pd.DataFrame, now: datetime | None = None) -> pd.DataFrame:
    df = df.copy()
    df.columns = [str(c).strip().lower().replace(" ", "_") for c in df.columns]
    if "adj_close" not in df.columns and "close" in df.columns:
        df["adj_close"] = df["close"]
    missing = [c for c in PRICE_COLS if c not in df.columns]
    if missing:
        raise ValueError(f"price frame missing columns {missing}")
    df = df[PRICE_COLS]
    idx = pd.DatetimeIndex(pd.to_datetime(df.index))
    if idx.tz is not None:
        idx = idx.tz_convert(IST).tz_localize(None)
    df.index = idx.normalize()
    df.index.name = "date"
    df = df[~df.index.duplicated(keep="last")].sort_index()
    df = df.dropna(subset=["close"])
    df = df[df["volume"].fillna(0) > 0]  # Yahoo emits zero-volume placeholder rows on some holidays
    return drop_partial_bar(df, now)


def drop_partial_bar(df: pd.DataFrame, now: datetime | None = None) -> pd.DataFrame:
    """If run during market hours, Yahoo hands back today's half-formed bar. Drop it:
    an intraday volume compared against full-day averages would always look 'low'."""
    now = now or datetime.now(IST)
    if len(df) and df.index[-1] == pd.Timestamp(now.date()) and now.time() < EOD_READY:
        return df.iloc[:-1]
    return df


# --------------------------------------------------------------------------- signals
def compute_signals(df: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    lb, slb = int(cfg["volume_lookback"]), int(cfg["sigma_lookback"])
    out = df.copy()
    out["pct_change"] = df["adj_close"].pct_change() * 100
    out["vol_avg"] = df["volume"].shift(1).rolling(lb, min_periods=max(5, lb // 2)).mean()
    out["vol_ratio"] = df["volume"] / out["vol_avg"]
    out["ret_std"] = out["pct_change"].shift(1).rolling(slb, min_periods=20).std()
    out["sigma"] = out["pct_change"] / out["ret_std"]
    return out


def _ok(x) -> bool:
    try:
        return x is not None and math.isfinite(float(x))
    except (TypeError, ValueError):
        return False


def _r(x, nd=2):
    return round(float(x), nd) if _ok(x) else None


def detect_alerts(symbol: str, sig: pd.DataFrame, cfg: dict, last_n: int = 1) -> list[dict]:
    """Scan the last `last_n` sessions. last_n=1 is 'today'; a larger value backfills an
    alert history (handy for the demo timeline)."""
    alerts = []
    lb = int(cfg["volume_lookback"])
    for date, r in sig.tail(last_n).iterrows():
        pc, vr, sg, va = r["pct_change"], r["vol_ratio"], r["sigma"], r["vol_avg"]
        triggers = []
        if _ok(pc) and abs(pc) >= cfg["price_move_pct"]:
            triggers.append({"type": "price_move", "value": _r(pc), "threshold": cfg["price_move_pct"]})
        if _ok(vr) and vr >= cfg["volume_multiple"] and _ok(va) and va >= cfg.get("min_avg_volume", 0):
            triggers.append({"type": "volume_spike", "value": _r(vr), "threshold": cfg["volume_multiple"]})
        st = cfg.get("sigma_threshold")
        if st and _ok(sg) and abs(sg) >= st and not any(t["type"] == "price_move" for t in triggers):
            triggers.append({"type": "unusual_for_stock", "value": _r(sg), "threshold": st})
        if not triggers:
            continue
        alerts.append({
            "symbol": symbol,
            "date": date.strftime("%Y-%m-%d"),
            "close": _r(r["close"]),
            "pct_change": _r(pc),
            "vol_ratio": _r(vr),
            "sigma": _r(sg),
            "triggers": triggers,
            "severity": _severity(triggers),
            "headline": _headline(pc, vr, sg, triggers, lb),
        })
    return alerts


def _severity(triggers: list[dict]) -> str:
    strength = max(abs(t["value"]) / t["threshold"] for t in triggers)
    return "high" if len(triggers) >= 2 or strength >= 2 else "medium"


def _headline(pc, vr, sg, triggers, lookback: int) -> str:
    bits = []
    if _ok(pc):
        bits.append(f"{pc:+.1f}% on the day")
    if _ok(vr) and any(t["type"] == "volume_spike" for t in triggers):
        bits.append(f"{vr:.1f}x its {lookback}-day avg volume")
    if _ok(sg) and abs(sg) >= 2:
        bits.append(f"a {abs(sg):.1f}σ move for this stock")
    return ", ".join(bits)


def snapshot(symbol: str, sig: pd.DataFrame) -> dict | None:
    """Latest-session card data for the frontend."""
    if sig.empty:
        return None
    r = sig.iloc[-1]
    year = sig["close"].tail(252)
    hi, lo = float(year.max()), float(year.min())
    return {
        "symbol": symbol,
        "date": sig.index[-1].strftime("%Y-%m-%d"),
        "close": _r(r["close"]),
        "pct_change": _r(r["pct_change"]),
        "vol_ratio": _r(r["vol_ratio"]),
        "sigma": _r(r["sigma"]),
        "high_52w": _r(hi),
        "low_52w": _r(lo),
        "pct_from_52w_high": _r((float(r["close"]) / hi - 1) * 100) if hi else None,
        "spark": [_r(x) for x in sig["close"].tail(30)],
    }
