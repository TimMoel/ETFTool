"""
SQLite snapshot layer for ETFTool.

One row per (date, ticker). Used by both the Streamlit app (for the
"what changed" diff strip + drawdown chart) and the nightly refresh
job (writes a row each weekday after LSE close).
"""

import json
import sqlite3
from datetime import date as _date
from pathlib import Path

import pandas as pd

DEFAULT_PATH = Path(__file__).parent / "data" / "history.sqlite"

SCHEMA = """
CREATE TABLE IF NOT EXISTS snapshots (
    date            TEXT NOT NULL,
    ticker          TEXT NOT NULL,
    price           REAL,
    ret_1w          REAL,
    ret_1m          REAL,
    ret_3m          REAL,
    drawdown        REAL,
    vol_30d         REAL,
    beta            REAL,
    dividend_yield  REAL,
    rating          TEXT,
    sentiment       TEXT,
    score           REAL,
    signals         TEXT,
    PRIMARY KEY (date, ticker)
);
CREATE INDEX IF NOT EXISTS idx_snapshots_ticker_date ON snapshots(ticker, date);
"""


def _connect(path=DEFAULT_PATH):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(path=DEFAULT_PATH):
    """Create the schema if it doesn't exist. Idempotent."""
    with _connect(path) as conn:
        conn.executescript(SCHEMA)


def insert_snapshot(ticker, fields, path=DEFAULT_PATH, snapshot_date=None):
    """Upsert today's snapshot for a single ticker. `fields` is a dict."""
    init_db(path)
    d = (snapshot_date or _date.today()).isoformat()
    signals_blob = json.dumps(fields.get("signals") or {})
    row = (
        d, ticker,
        fields.get("price"),
        fields.get("ret_1w"), fields.get("ret_1m"), fields.get("ret_3m"),
        fields.get("drawdown"), fields.get("vol_30d"),
        fields.get("beta"), fields.get("dividend_yield"),
        fields.get("rating"), fields.get("sentiment"),
        fields.get("score"), signals_blob,
    )
    with _connect(path) as conn:
        conn.execute(
            """INSERT OR REPLACE INTO snapshots
               (date, ticker, price, ret_1w, ret_1m, ret_3m, drawdown, vol_30d,
                beta, dividend_yield, rating, sentiment, score, signals)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            row,
        )


def latest_snapshot(ticker, path=DEFAULT_PATH):
    """Most recent snapshot for ticker, or None."""
    with _connect(path) as conn:
        cur = conn.execute(
            "SELECT * FROM snapshots WHERE ticker=? ORDER BY date DESC LIMIT 1",
            (ticker,),
        )
        row = cur.fetchone()
        return _row_to_dict(row)


def previous_snapshot(ticker, path=DEFAULT_PATH):
    """Second-most-recent snapshot — the one we diff against."""
    with _connect(path) as conn:
        cur = conn.execute(
            "SELECT * FROM snapshots WHERE ticker=? ORDER BY date DESC LIMIT 1 OFFSET 1",
            (ticker,),
        )
        row = cur.fetchone()
        return _row_to_dict(row)


def diff_vs_previous(path=DEFAULT_PATH):
    """
    Compare every ticker's latest snapshot vs its previous snapshot.
    Returns a list of change dicts the UI/alert layer can render:
      {ticker, kind, detail, severity}
        kind     in {"rating", "high", "low", "signal"}
        severity in {"up", "down", "neutral"}
    """
    init_db(path)
    changes = []
    with _connect(path) as conn:
        tickers = [r["ticker"] for r in conn.execute(
            "SELECT DISTINCT ticker FROM snapshots"
        )]
    for ticker in tickers:
        cur = latest_snapshot(ticker, path)
        prev = previous_snapshot(ticker, path)
        if not cur or not prev:
            continue

        # Rating flip
        if (cur.get("rating") or "").lower() != (prev.get("rating") or "").lower():
            sev = _rating_severity(prev.get("rating"), cur.get("rating"))
            changes.append({
                "ticker": ticker, "kind": "rating", "severity": sev,
                "detail": f"{(prev.get('rating') or '—').upper()} → {(cur.get('rating') or '—').upper()}",
            })

        # New 1M-ish high/low (proxy: today's price exceeds the prior 22 sessions)
        history_df = history(ticker, days=30, path=path)
        if len(history_df) >= 2:
            prior = history_df.iloc[:-1]["price"]
            today_price = cur.get("price")
            if today_price is not None and len(prior) > 0:
                if today_price >= float(prior.max()):
                    changes.append({"ticker": ticker, "kind": "high",
                                    "severity": "up", "detail": "new 1-month high"})
                elif today_price <= float(prior.min()):
                    changes.append({"ticker": ticker, "kind": "low",
                                    "severity": "down", "detail": "new 1-month low"})

        # Signal flips (new flag turned on or off)
        cur_sig = _safe_json(cur.get("signals"))
        prev_sig = _safe_json(prev.get("signals"))
        for flag in sorted(set(cur_sig) | set(prev_sig)):
            if bool(cur_sig.get(flag)) != bool(prev_sig.get(flag)):
                turned_on = bool(cur_sig.get(flag))
                sev = _signal_severity(flag, turned_on)
                changes.append({
                    "ticker": ticker, "kind": "signal", "severity": sev,
                    "detail": f"{flag} {'ON' if turned_on else 'off'}",
                })
    return changes


def history(ticker, days=90, path=DEFAULT_PATH):
    """Return a DataFrame of (date, price) for `ticker`, last `days` rows."""
    init_db(path)
    with _connect(path) as conn:
        df = pd.read_sql_query(
            "SELECT date, price FROM snapshots WHERE ticker=? "
            "ORDER BY date DESC LIMIT ?",
            conn, params=(ticker, days),
        )
    if df.empty:
        return df
    df = df.sort_values("date").reset_index(drop=True)
    df["date"] = pd.to_datetime(df["date"])
    return df


def all_tickers(path=DEFAULT_PATH):
    init_db(path)
    with _connect(path) as conn:
        return [r["ticker"] for r in conn.execute(
            "SELECT DISTINCT ticker FROM snapshots ORDER BY ticker"
        )]


# ---------------------------------------------------------------- helpers

def _row_to_dict(row):
    if row is None:
        return None
    d = dict(row)
    return d


def _safe_json(blob):
    if not blob:
        return {}
    try:
        v = json.loads(blob)
        return v if isinstance(v, dict) else {}
    except Exception:
        return {}


def _rating_severity(prev, curr):
    order = {"sell": 0, "hold": 1, "buy": 2}
    p = order.get((prev or "").lower(), 1)
    c = order.get((curr or "").lower(), 1)
    if c > p: return "up"
    if c < p: return "down"
    return "neutral"


_BULLISH_FLAGS = {
    "golden_cross", "macd_bull_cross", "rsi_oversold",
    "momentum_1m_pos", "near_52w_high",
}
_BEARISH_FLAGS = {
    "death_cross", "macd_bear_cross", "rsi_overbought",
    "deep_drawdown", "high_vol",
}


def _signal_severity(flag, turned_on):
    """A bullish flag turning on is 'up'; a bearish flag turning on is 'down'."""
    if flag in _BULLISH_FLAGS:
        return "up" if turned_on else "down"
    if flag in _BEARISH_FLAGS:
        return "down" if turned_on else "up"
    return "neutral"
