"""SQLite store: EOD prices, announcements, and small run metadata (cache markers)."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pandas as pd

from .config import ROOT

DB_PATH = ROOT / "data" / "finn.db"
PRICE_COLS = ["open", "high", "low", "close", "adj_close", "volume"]

SCHEMA = """
CREATE TABLE IF NOT EXISTS prices (
    symbol TEXT, date TEXT, open REAL, high REAL, low REAL, close REAL, adj_close REAL, volume REAL,
    PRIMARY KEY (symbol, date)
);
CREATE TABLE IF NOT EXISTS announcements (
    id TEXT PRIMARY KEY, symbol TEXT, company TEXT, source TEXT, filed_at TEXT,
    exchange_category TEXT, subject TEXT, pdf_url TEXT,
    category TEXT, secondary TEXT, tags TEXT, needs_llm INTEGER, fetched_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_ann_symbol_time ON announcements (symbol, filed_at);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
"""

_ANN_COLS = ["id", "symbol", "company", "source", "filed_at", "exchange_category", "subject",
             "pdf_url", "category", "secondary", "tags", "needs_llm", "fetched_at"]


class Store:
    def __init__(self, path: str | Path = DB_PATH):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(path))
        self.conn.executescript(SCHEMA)

    # ---------- prices ----------
    def upsert_prices(self, symbol: str, df: pd.DataFrame) -> int:
        if df is None or df.empty:
            return 0
        rows = [
            (symbol, idx.strftime("%Y-%m-%d"), *[None if pd.isna(v) else float(v) for v in vals])
            for idx, vals in zip(df.index, df[PRICE_COLS].itertuples(index=False))
        ]
        with self.conn:
            self.conn.executemany("INSERT OR REPLACE INTO prices VALUES (?,?,?,?,?,?,?,?)", rows)
        return len(rows)

    def load_prices(self, symbol: str) -> pd.DataFrame:
        df = pd.read_sql_query(
            "SELECT date, open, high, low, close, adj_close, volume FROM prices WHERE symbol=? ORDER BY date",
            self.conn, params=(symbol,), parse_dates=["date"],
        )
        return df.set_index("date")

    # ---------- announcements ----------
    def upsert_announcements(self, rows: list[dict]) -> int:
        """Insert new filings; refresh classification on ones we've already seen.
        Returns how many were genuinely new."""
        if not rows:
            return 0
        ids = list({r["id"] for r in rows})
        existing: set[str] = set()
        for i in range(0, len(ids), 500):
            part = ids[i:i + 500]
            q = f"SELECT id FROM announcements WHERE id IN ({','.join('?' * len(part))})"
            existing |= {x[0] for x in self.conn.execute(q, part)}
        payload = [self._to_db(r) for r in rows]
        with self.conn:
            self.conn.executemany(
                f"INSERT INTO announcements ({','.join(_ANN_COLS)}) VALUES ({','.join(':' + c for c in _ANN_COLS)}) "
                "ON CONFLICT(id) DO UPDATE SET category=excluded.category, secondary=excluded.secondary, "
                "tags=excluded.tags, needs_llm=excluded.needs_llm",
                payload,
            )
        return len(set(ids) - existing)

    def announcements_between(self, start_iso: str, end_iso: str, symbols: list[str] | None = None) -> list[dict]:
        q = f"SELECT {','.join(_ANN_COLS)} FROM announcements WHERE filed_at >= ? AND filed_at < ?"
        params: list = [start_iso, end_iso]
        if symbols:
            q += f" AND symbol IN ({','.join('?' * len(symbols))})"
            params += symbols
        q += " ORDER BY filed_at DESC"
        return [self._from_db(dict(zip(_ANN_COLS, row))) for row in self.conn.execute(q, params)]

    @staticmethod
    def _to_db(r: dict) -> dict:
        d = {c: r.get(c) for c in _ANN_COLS}
        d["secondary"] = json.dumps(r.get("secondary") or [])
        d["tags"] = json.dumps(r.get("tags") or [])
        d["needs_llm"] = int(bool(r.get("needs_llm")))
        return d

    @staticmethod
    def _from_db(d: dict) -> dict:
        d["secondary"] = json.loads(d["secondary"] or "[]")
        d["tags"] = json.loads(d["tags"] or "[]")
        d["needs_llm"] = bool(d["needs_llm"])
        return d

    # ---------- meta ----------
    def get_meta(self, key: str) -> str | None:
        row = self.conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return row[0] if row else None

    def set_meta(self, key: str, value: str) -> None:
        with self.conn:
            self.conn.execute("INSERT OR REPLACE INTO meta VALUES (?, ?)", (key, value))
