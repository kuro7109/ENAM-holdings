"""Portfolio + alert-threshold config, loaded from config/portfolio.yaml."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = ROOT / "config" / "portfolio.yaml"

# Defaults. Every value can be overridden globally (`alerts:` in the YAML) or per stock.
DEFAULT_ALERTS = {
    "price_move_pct": 4.0,    # |daily move| >= X%                        -> alert
    "volume_multiple": 2.0,   # volume >= k x trailing average            -> alert
    "volume_lookback": 20,    # sessions in that trailing average
    "sigma_threshold": 3.0,   # move >= N std-devs of the stock's OWN daily moves (null = off)
    "sigma_lookback": 60,     # sessions used to estimate that std-dev
    "min_avg_volume": 0,      # ignore volume spikes on very illiquid names
}


@dataclass
class Company:
    symbol: str
    name: str = ""
    sector: str = ""
    bse_code: str | None = None
    yf_symbol: str | None = None          # only if Yahoo's symbol differs from NSE's
    alerts: dict = field(default_factory=dict)

    @property
    def yf_ticker(self) -> str:
        return self.yf_symbol or f"{self.symbol}.NS"


@dataclass
class Config:
    companies: list[Company]
    research: list[Company]
    alerts: dict

    def alerts_for(self, symbol: str) -> dict:
        merged = {**DEFAULT_ALERTS, **(self.alerts or {})}
        for c in self.companies:
            if c.symbol == symbol:
                merged.update(c.alerts or {})
        return merged


def _company(d: dict) -> Company:
    return Company(
        symbol=str(d["symbol"]).strip().upper(),
        name=d.get("name", ""),
        sector=d.get("sector", ""),
        bse_code=str(d["bse_code"]) if d.get("bse_code") else None,
        yf_symbol=d.get("yf_symbol"),
        alerts=d.get("alerts") or {},
    )


def load_config(path: str | Path | None = None) -> Config:
    p = Path(path) if path else DEFAULT_CONFIG
    raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    return Config(
        companies=[_company(c) for c in raw.get("portfolio", [])],
        research=[_company(c) for c in raw.get("research", [])],
        alerts=raw.get("alerts") or {},
    )
