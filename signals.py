"""
Quantitative buy/sell signals for ETFTool.

Pure functions — no Streamlit, no I/O. Given a price-history DataFrame and a
fundamentals dict, return a flat dict of boolean signal flags plus a single
composite score (0–100, higher = more attractive).
"""

import pandas as pd

# pandas_ta is optional at import time so the headless refresh job can fall
# back to NumPy-only computations if the dep isn't installed yet.
try:
    import pandas_ta as ta  # type: ignore
    _HAS_TA = True
except Exception:
    ta = None
    _HAS_TA = False


SIGNAL_KEYS = [
    "momentum_1m_pos",
    "near_52w_high",
    "deep_drawdown",
    "high_vol",
    "volume_spike",
    "golden_cross",
    "death_cross",
    "rsi_overbought",
    "rsi_oversold",
    "macd_bull_cross",
    "macd_bear_cross",
]


def _empty_signals():
    return {k: False for k in SIGNAL_KEYS}


def compute_signals(history_df, fundamentals=None, volume_series=None):
    """
    history_df: DataFrame with columns ['date','price'] in chronological order.
    fundamentals: dict with ret_1m, drawdown, vol_30d, high_52w, etc.
    volume_series: optional pd.Series of daily volume aligned with history_df.

    Returns a dict of bool flags. Missing data → flag stays False.
    """
    flags = _empty_signals()
    fundamentals = fundamentals or {}

    if history_df is None or len(history_df) < 5:
        return flags

    close = pd.to_numeric(history_df["price"], errors="coerce").dropna()
    if close.empty:
        return flags

    flags["momentum_1m_pos"] = (fundamentals.get("ret_1m") or 0) > 0
    flags["high_vol"]        = (fundamentals.get("vol_30d") or 0) > 25
    flags["deep_drawdown"]   = (fundamentals.get("drawdown") or 0) < -15

    high_52w = fundamentals.get("high_52w")
    current  = float(close.iloc[-1])
    if high_52w:
        flags["near_52w_high"] = (current / float(high_52w)) >= 0.97

    # Volume spike — last bar > 2x trailing 90-day average
    if volume_series is not None and len(volume_series) >= 30:
        vol = pd.to_numeric(volume_series, errors="coerce").dropna()
        if len(vol) >= 30:
            avg = float(vol.iloc[-91:-1].mean()) if len(vol) > 91 else float(vol.iloc[:-1].mean())
            today = float(vol.iloc[-1])
            if avg > 0:
                flags["volume_spike"] = today >= 2 * avg

    # 50/200 SMA cross — fired only if cross happened in the last 5 sessions
    if len(close) >= 205:
        sma50  = close.rolling(50).mean()
        sma200 = close.rolling(200).mean()
        diff = (sma50 - sma200).dropna()
        if len(diff) >= 6:
            recent = diff.iloc[-5:]
            prior  = diff.iloc[-6:-5].iloc[0]
            if prior <= 0 and (recent > 0).any():
                flags["golden_cross"] = True
            if prior >= 0 and (recent < 0).any():
                flags["death_cross"] = True

    # RSI(14) — pandas_ta if available, else NumPy fallback
    rsi_last = _rsi(close, 14)
    if rsi_last is not None:
        flags["rsi_overbought"] = rsi_last > 70
        flags["rsi_oversold"]   = rsi_last < 30

    # MACD(12,26,9) cross — pandas_ta only (cheap to skip if dep missing)
    if _HAS_TA and len(close) >= 35:
        try:
            macd_df = ta.macd(close, fast=12, slow=26, signal=9)
            if macd_df is not None and len(macd_df) >= 2:
                line_col = [c for c in macd_df.columns if c.startswith("MACD_") and not c.startswith("MACDh_") and not c.startswith("MACDs_")][0]
                sig_col  = [c for c in macd_df.columns if c.startswith("MACDs_")][0]
                d_today = macd_df[line_col].iloc[-1] - macd_df[sig_col].iloc[-1]
                d_prev  = macd_df[line_col].iloc[-2] - macd_df[sig_col].iloc[-2]
                if d_prev <= 0 and d_today > 0:
                    flags["macd_bull_cross"] = True
                if d_prev >= 0 and d_today < 0:
                    flags["macd_bear_cross"] = True
        except Exception:
            pass

    return flags


def composite_score(rating, flags):
    """Map a Claude rating + signal flags to a 0–100 attractiveness score."""
    score = 50.0
    r = (rating or "hold").lower()
    if r == "buy":  score += 20
    if r == "sell": score -= 20

    f = flags or {}
    if f.get("momentum_1m_pos"):  score += 10
    if f.get("macd_bull_cross"):  score += 10
    if f.get("macd_bear_cross"):  score -= 10
    if f.get("rsi_oversold"):     score += 10
    if f.get("rsi_overbought"):   score -= 10
    if f.get("golden_cross"):     score +=  5
    if f.get("death_cross"):      score -=  5
    if f.get("deep_drawdown"):    score -= 10  # treat drawdown as risk, not buy-the-dip
    if f.get("near_52w_high"):    score +=  5
    if f.get("high_vol"):         score -=  5

    return max(0.0, min(100.0, score))


# ---------------------------------------------------------------- helpers

def _rsi(close, period=14):
    """Last RSI value, computed with pandas_ta if present, else Wilder's RSI."""
    if len(close) < period + 1:
        return None
    if _HAS_TA:
        try:
            series = ta.rsi(close, length=period)
            if series is None or series.dropna().empty:
                return None
            return float(series.dropna().iloc[-1])
        except Exception:
            pass
    # NumPy fallback — Wilder's smoothing
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, pd.NA)
    rsi = 100 - (100 / (1 + rs))
    s = rsi.dropna()
    return float(s.iloc[-1]) if len(s) else None
