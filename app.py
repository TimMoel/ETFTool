"""
ETF Tracker — Streamlit dashboard
A clean, modern portfolio sentiment dashboard for a UK ETF investor.

Layout / styling notes
----------------------
- Single CSS override block at the top, no inline styles scattered through.
- Native Streamlit components only (tabs, columns, metrics, expanders).
- 4-tab structure: Positions / Performance / News & signals / Analysis.
- Sidebar holds all controls (sliders, add/remove, credits, action buttons).
"""

import streamlit as st
import yfinance as yf
import plotly.graph_objects as go
import plotly.express as px
import pandas as pd
import numpy as np
import anthropic
import json
from datetime import datetime, timedelta, date as _date
from pathlib import Path

import db
import signals as sg
import core

# =============================================================================
# Holdings persistence (cost basis: avg_price + units per ticker)
# =============================================================================

HOLDINGS_PATH = Path(__file__).parent / "data" / "holdings.json"


def load_holdings() -> dict:
    """Return {ticker: {avg_price, units}} from disk, or {} if missing/corrupt."""
    if HOLDINGS_PATH.exists():
        try:
            return json.loads(HOLDINGS_PATH.read_text())
        except Exception:
            return {}
    return {}


def save_holdings(etfs: dict) -> None:
    """Persist avg_price + units per ticker to data/holdings.json (gitignored)."""
    HOLDINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        t: {"avg_price": v["avg_price"], "units": v["units"]}
        for t, v in etfs.items()
        if v.get("avg_price") is not None and v.get("units") is not None
    }
    HOLDINGS_PATH.write_text(json.dumps(payload, indent=2))

# =============================================================================
# Page config + global CSS override
# =============================================================================

st.set_page_config(
    page_title="ETF Tracker",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
    <style>
    /* --- design tokens ------------------------------------------------- */
    :root {
        --bg: #F1F3F6;
        --surface: #FFFFFF;
        --border: #E5E7EB;
        --border-strong: #CBD5E1;
        --text: #0F172A;
        --muted: #64748B;
        --muted-2: #94A3B8;
        --buy: #00C896;  --buy-bg: #E8FAF4;
        --hold: #F59E0B; --hold-bg: #FEF3C7;
        --sell: #EF4444; --sell-bg: #FEF2F2;
    }

    /* --- canvas -------------------------------------------------------- */
    html, body, [data-testid="stAppViewContainer"] {
        background: #F1F3F6 !important;
        font-family: "Helvetica Neue", Helvetica, Arial, sans-serif;
        color: #0F172A;
    }
    [data-testid="stHeader"] { background: transparent; }
    .main .block-container {
        padding-top: 1.5rem;
        padding-bottom: 4rem;
        max-width: 1480px;
    }

    /* --- typography scale --------------------------------------------- */
    h1 { font-size: 24px !important; font-weight: 500 !important;
         letter-spacing: -0.015em; color: #0F172A; margin-bottom: 4px; }
    h2 { font-size: 16px !important; font-weight: 600 !important; color: #0F172A; }
    h3 { font-size: 14px !important; font-weight: 600 !important; color: #0F172A; }
    p, div, span, label { color: #0F172A; }

    /* small uppercase section labels (used via st.caption) */
    [data-testid="stCaptionContainer"] {
        font-size: 11px !important;
        font-weight: 600 !important;
        color: #64748B !important;
        text-transform: uppercase;
        letter-spacing: 0.08em;
    }

    /* --- sidebar ------------------------------------------------------- */
    [data-testid="stSidebar"] {
        background: #FFFFFF;
        border-right: 1px solid #E5E7EB;
    }
    [data-testid="stSidebar"] .block-container { padding-top: 1.5rem; }
    [data-testid="stSidebar"] h2 { font-size: 16px !important; }

    /* --- metric cards -------------------------------------------------- */
    [data-testid="stMetric"] {
        background: #FFFFFF;
        border: 1px solid #E5E7EB;
        border-radius: 10px;
        padding: 14px 16px;
        box-shadow: 0 1px 0 rgba(15,23,42,0.04), 0 1px 2px rgba(15,23,42,0.04);
    }
    [data-testid="stMetricLabel"] {
        font-size: 11px !important;
        font-weight: 600 !important;
        color: #64748B !important;
        text-transform: uppercase;
        letter-spacing: 0.08em;
    }
    [data-testid="stMetricValue"] {
        font-family: "JetBrains Mono", ui-monospace, SFMono-Regular, Menlo, monospace !important;
        font-size: 22px !important;
        font-weight: 600 !important;
        letter-spacing: -0.02em;
        color: #0F172A !important;
    }
    [data-testid="stMetricDelta"] { font-size: 12px !important; }

    /* --- tabs ---------------------------------------------------------- */
    [data-testid="stTabs"] [data-baseweb="tab-list"] {
        gap: 24px;
        border-bottom: 1px solid #E5E7EB;
    }
    [data-testid="stTabs"] [data-baseweb="tab"] {
        background: transparent;
        padding: 12px 0;
        font-size: 14px;
        font-weight: 500;
        color: #64748B;
    }
    [data-testid="stTabs"] [aria-selected="true"] {
        color: #0F172A;
        border-bottom: 2px solid #0F172A;
    }

    /* --- buttons ------------------------------------------------------- */
    [data-testid="stSidebar"] .stButton button {
        width: 100%;
        background: #FFFFFF;
        color: #0F172A !important;
        border: 1px solid #CBD5E1;
        border-radius: 6px;
        padding: 9px 14px;
        font-size: 13px;
        font-weight: 500;
        transition: all .12s ease;
    }
    [data-testid="stSidebar"] .stButton button:hover {
        background: #F1F3F6;
        border-color: #0F172A;
    }
    [data-testid="stSidebar"] .stButton button[kind="primary"],
    [data-testid="stSidebar"] .stButton button[data-testid="baseButton-primary"] {
        background: #0F172A !important;
        color: #FFFFFF !important;
        border-color: #0F172A !important;
    }
    [data-testid="stSidebar"] .stButton button[kind="primary"] p,
    [data-testid="stSidebar"] .stButton button[data-testid="baseButton-primary"] p {
        color: #FFFFFF !important;
    }

    /* --- expander ------------------------------------------------------ */
    [data-testid="stExpander"] {
        border: 1px solid #E5E7EB;
        border-radius: 6px;
        background: #FFFFFF;
    }
    [data-testid="stExpander"] summary { font-size: 13px; }

    /* --- progress bar -------------------------------------------------- */
    [data-testid="stProgressBar"] > div > div { background: #0F172A; }

    /* --- slider -------------------------------------------------------- */
    [data-testid="stSlider"] [data-baseweb="slider"] [role="slider"] {
        background: #0F172A;
        border: 2px solid #FFFFFF;
        box-shadow: 0 0 0 1px #0F172A;
    }

    /* --- rating pill --------------------------------------------------- */
    .rating-pill {
        display: inline-block;
        padding: 4px 10px;
        border-radius: 4px;
        font-size: 11px;
        font-weight: 700;
        letter-spacing: 0.08em;
        white-space: nowrap;
        font-family: "Helvetica Neue", Helvetica, Arial, sans-serif;
    }
    .rating-buy  { color: #00C896; background: #E8FAF4; }
    .rating-hold { color: #F59E0B; background: #FEF3C7; }
    .rating-sell { color: #EF4444; background: #FEF2F2; }

    /* mono numbers helper */
    .mono { font-family: "JetBrains Mono", ui-monospace, SFMono-Regular, Menlo, monospace;
            font-feature-settings: "tnum"; }

    /* hide the streamlit toolbar branding chrome we don't want */
    [data-testid="stToolbar"] { right: 1rem; }
    footer { visibility: hidden; }

    /* --- additional breathing room for cards and layout ---------------- */
    .main .block-container { padding-left: 2rem; padding-right: 2rem; }
    [data-testid="stVerticalBlockBorderWrapper"] > div {
        padding: 14px !important;
    }
    [data-testid="stSidebar"] [data-testid="stVerticalBlock"] { gap: 0.25rem; }

    /* --- sleek sidebar allocation inputs ------------------------------- */
    [data-testid="stSidebar"] [data-testid="stNumberInput"] label {
        font-family: "JetBrains Mono", ui-monospace, SFMono-Regular, Menlo, monospace !important;
        font-size: 12px !important;
        font-weight: 600 !important;
        color: #0F172A !important;
        text-transform: none !important;
        letter-spacing: 0 !important;
        margin-bottom: 0 !important;
        padding-bottom: 0 !important;
    }
    [data-testid="stSidebar"] [data-testid="stNumberInput"] input {
        font-family: "JetBrains Mono", ui-monospace, SFMono-Regular, Menlo, monospace !important;
        text-align: right;
        font-size: 13px;
        padding: 4px 8px !important;
    }
    [data-testid="stSidebar"] [data-testid="stNumberInput"] {
        margin-bottom: 2px;
    }
    /* breathing space above each sidebar section caption */
    [data-testid="stSidebar"] [data-testid="stCaptionContainer"] {
        margin-top: 14px;
        margin-bottom: 4px;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# Pull JetBrains Mono webfont
st.markdown(
    """
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;600;700&display=swap" rel="stylesheet">
    """,
    unsafe_allow_html=True,
)

# =============================================================================
# Constants
# =============================================================================

API_MIN_REFRESH_HRS   = 6
API_COST_PER_NEWS     = 0.01
API_COST_PER_ANALYSIS = 0.001

DEFAULT_ETFS = {
    "VWRP": {"name":"Global all-world",  "yahoo":"VWRP.L","cat":"Core"},
    "XMWX": {"name":"Developed ex-US",   "yahoo":"XMWX.L","cat":"Core"},
    "EMIM": {"name":"Emerging markets",  "yahoo":"EMIM.L","cat":"Core"},
    "CSH2": {"name":"Cash/overnight",    "yahoo":"CSH2.L","cat":"Core"},
    "SPDR": {"name":"S&P 500 UCITS",     "yahoo":"SPDR.L","cat":"Core"},
    "VEUR": {"name":"Europe",            "yahoo":"VEUR.L","cat":"Core"},
    "NATP": {"name":"Defence global",    "yahoo":"NATP.L","cat":"Satellite"},
    "NUCG": {"name":"Nuclear/uranium",   "yahoo":"NUCG.L","cat":"Satellite"},
    "WDEP": {"name":"Defence Europe",    "yahoo":"WDEP.L","cat":"Satellite"},
    "BUGG": {"name":"Cybersecurity",     "yahoo":"BUGG.L","cat":"Satellite"},
    "ARMG": {"name":"Defence tech",      "yahoo":"ARMG.L","cat":"Satellite"},
    "RBTX": {"name":"Robotics",          "yahoo":"RBTX.L","cat":"Satellite"},
}

DEFAULT_ALLOCS = {
    "VWRP":47.0,"XMWX":10.0,"EMIM":10.0,"CSH2":5.0,
    "SPDR":6.0,"VEUR":4.0,"NATP":3.0,"NUCG":3.0,
    "WDEP":3.0,"BUGG":3.0,"ARMG":3.0,"RBTX":3.0,
}

# =============================================================================
# Session state initialisation
# =============================================================================

if "etfs" not in st.session_state:
    st.session_state.etfs = DEFAULT_ETFS.copy()
    # Merge persisted holdings (avg_price + units) into the ETF metadata
    for _t, _h in load_holdings().items():
        if _t in st.session_state.etfs:
            st.session_state.etfs[_t]["avg_price"] = _h.get("avg_price")
            st.session_state.etfs[_t]["units"]     = _h.get("units")
if "allocs"          not in st.session_state: st.session_state.allocs = DEFAULT_ALLOCS.copy()
if "news_data"       not in st.session_state: st.session_state.news_data = {}
if "analysis"        not in st.session_state: st.session_state.analysis = ""
if "price_data"      not in st.session_state: st.session_state.price_data = {}
if "signals_data"    not in st.session_state: st.session_state.signals_data = {}
if "changes"         not in st.session_state: st.session_state.changes = []
if "last_news_fetch" not in st.session_state: st.session_state.last_news_fetch = None
if "api_spend"       not in st.session_state: st.session_state.api_spend = 0.0

# Make sure the snapshot DB schema exists on first run.
db.init_db()

# =============================================================================
# API key
# =============================================================================

try:
    api_key = st.secrets["ANTHROPIC_API_KEY"]
except Exception:
    api_key = None

# =============================================================================
# Data functions (preserved from original)
# =============================================================================

def hours_since_last_fetch():
    if not st.session_state.last_news_fetch: return None
    return (datetime.now() - st.session_state.last_news_fetch).total_seconds() / 3600

@st.cache_data(ttl=900)
def fetch_price_data(etf_pairs):
    """Cached Streamlit wrapper around core.fetch_price_data_raw."""
    return core.fetch_price_data_raw(etf_pairs)

def fetch_news_and_ratings(etfs):
    """Streamlit wrapper around core.fetch_news_and_ratings_raw with UI fallback."""
    try:
        return core.fetch_news_and_ratings_raw(etfs, api_key)
    except Exception as e:
        st.error(f"News fetch failed: {e}")
        return {t: {"sentiment": "neutral", "rating": "hold", "news": [], "drivers": ""} for t in etfs}

def generate_analysis(allocs, news, price_data, etfs):
    """Generate Claude portfolio analysis with enriched yfinance fundamentals."""
    client = anthropic.Anthropic(api_key=api_key)
    alloc_str = ", ".join(f"{t} {v}%" for t, v in allocs.items())

    def _fmt(d):
        parts = [
            f"1W={d['ret_1w']:+.1f}%",
            f"1M={d['ret_1m']:+.1f}%",
            f"3M={d['ret_3m']:+.1f}%",
        ]
        if d.get("year_change") is not None:
            parts.append(f"12M={d['year_change']:+.1f}%")
        if d.get("high_52w") and d.get("low_52w"):
            parts.append(f"52wk={d['low_52w']:.2f}–{d['high_52w']:.2f}")
        if d.get("drawdown") is not None:
            parts.append(f"drawdown={d['drawdown']:+.1f}%")
        if d.get("vol_30d") is not None:
            parts.append(f"vol={d['vol_30d']:.1f}%")
        if d.get("beta") is not None:
            parts.append(f"β={d['beta']:.2f}")
        if d.get("dividend_yield") is not None:
            parts.append(f"yield={d['dividend_yield']:.2f}%")
        return " | ".join(parts)

    price_str = "".join(f"{t}: {_fmt(d)}\n" for t, d in price_data.items() if d)
    sell_list = [t for t, v in news.items() if v.get("rating") == "sell"]
    buy_list  = [t for t, v in news.items() if v.get("rating") == "buy"]
    high_news = [(t, i["text"]) for t, v in news.items() for i in v.get("news", [])
                 if isinstance(i, dict) and i.get("impact") == "high"]
    ratings_str = ", ".join(
        f"{t}:{v.get('rating','hold').upper()}" for t, v in news.items() if v
    )
    drivers_str = " | ".join(
        f"{t}: {v.get('drivers','')}" for t, v in news.items() if v and v.get("drivers")
    )
    msg = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1000,
        messages=[{"role": "user", "content":
            f"Portfolio analyst. Allocation: {alloc_str}\n"
            f"Ratings: {ratings_str}\n"
            f"Price & fundamentals:\n{price_str}\n"
            f"Buy signals: {buy_list}\nSell signals: {sell_list}\n"
            f"High-impact news: {high_news}\n"
            f"Key drivers: {drivers_str}\n\n"
            "Write 3 concise paragraphs (≤120 words each): "
            "(1) overall portfolio health citing momentum, drawdown, volatility; "
            "(2) immediate attention items with specific tickers and numbers; "
            "(3) top 3 watch items with one-line action each. "
            "Be specific. No bullets. No preamble."}],
    )
    return msg.content[0].text

# =============================================================================
# Signals + snapshot wiring
# =============================================================================

def build_signals_for_all(price_data, news_data):
    """Run compute_signals + composite_score for every ETF. Returns {ticker: {flags, score}}."""
    out = {}
    for ticker, pd_ in price_data.items():
        if not pd_:
            out[ticker] = {"flags": sg._empty_signals(), "score": 50.0}
            continue
        flags = sg.compute_signals(
            pd_.get("history"),
            fundamentals=pd_,
            volume_series=pd_.get("volume"),
        )
        rating = (news_data.get(ticker) or {}).get("rating", "hold")
        out[ticker] = {"flags": flags, "score": sg.composite_score(rating, flags)}
    return out


def persist_snapshots(etfs, price_data, news_data, signals_data):
    """Write one snapshot row per ticker for today. Silent on failure (DB is non-critical)."""
    try:
        for ticker in etfs:
            pd_ = price_data.get(ticker) or {}
            news = news_data.get(ticker) or {}
            sig = signals_data.get(ticker) or {}
            db.insert_snapshot(ticker, {
                "price": pd_.get("current"),
                "ret_1w": pd_.get("ret_1w"),
                "ret_1m": pd_.get("ret_1m"),
                "ret_3m": pd_.get("ret_3m"),
                "drawdown": pd_.get("drawdown"),
                "vol_30d": pd_.get("vol_30d"),
                "beta": pd_.get("beta"),
                "dividend_yield": pd_.get("dividend_yield"),
                "rating": news.get("rating"),
                "sentiment": news.get("sentiment"),
                "score": sig.get("score"),
                "signals": sig.get("flags"),
            })
    except Exception as e:
        st.warning(f"Snapshot save failed (non-fatal): {e}")


SIGNAL_ICONS = {
    "golden_cross":    ("↑MA",   "#00C896", "#E8FAF4", "50d crossed above 200d"),
    "death_cross":     ("↓MA",   "#EF4444", "#FEF2F2", "50d crossed below 200d"),
    "macd_bull_cross": ("MACD↑", "#00C896", "#E8FAF4", "MACD bullish cross"),
    "macd_bear_cross": ("MACD↓", "#EF4444", "#FEF2F2", "MACD bearish cross"),
    "rsi_overbought":  ("RSI▲",  "#F59E0B", "#FEF3C7", "RSI > 70"),
    "rsi_oversold":    ("RSI▼",  "#3B82F6", "#EFF6FF", "RSI < 30"),
    "deep_drawdown":   ("DD",    "#EF4444", "#FEF2F2", "drawdown < −15%"),
    "high_vol":        ("σ",     "#F59E0B", "#FEF3C7", "30d vol > 25%"),
    "volume_spike":    ("⚡",    "#3B82F6", "#EFF6FF", "volume > 2× 90d avg"),
    "near_52w_high":   ("52w↑",  "#00C896", "#E8FAF4", "within 3% of 52-week high"),
    "momentum_1m_pos": ("1M+",   "#00C896", "#E8FAF4", "1-month return > 0"),
}


def render_signal_chips(flags):
    """Render small flag chips for any active signal."""
    on = [k for k in sg.SIGNAL_KEYS if flags.get(k)]
    if not on:
        return ""
    chips = []
    for k in on:
        if k not in SIGNAL_ICONS: continue
        label, fg, bg, tip = SIGNAL_ICONS[k]
        chips.append(
            f"<span title='{tip}' style='background:{bg};color:{fg};font-size:9px;font-weight:700;"
            f"padding:2px 5px;border-radius:3px;letter-spacing:0.04em;margin-right:3px;"
            f"display:inline-block;white-space:nowrap;'>{label}</span>"
        )
    return "".join(chips)


def render_changes_strip(changes):
    """Render the 'what changed since last refresh' strip; returns HTML or ''."""
    if not changes:
        return ""
    sev_style = {
        "up":      ("#00C896", "#E8FAF4"),
        "down":    ("#EF4444", "#FEF2F2"),
        "neutral": ("#F59E0B", "#FEF3C7"),
    }
    pills = []
    for c in changes:
        fg, bg = sev_style.get(c.get("severity", "neutral"))
        pills.append(
            f"<span style='background:{bg};color:{fg};font-size:11px;font-weight:600;"
            f"padding:4px 8px;border-radius:6px;margin:0 6px 6px 0;display:inline-block;"
            f"white-space:nowrap;font-family:Helvetica Neue,Helvetica,Arial,sans-serif;'>"
            f"<span class='mono' style='font-weight:700;'>{c['ticker']}</span> · {c['detail']}</span>"
        )
    return (
        "<div style='background:#FFFFFF;border:1px solid #E5E7EB;border-radius:10px;"
        "padding:12px 14px;margin-bottom:16px;'>"
        "<div style='font-size:11px;font-weight:600;color:#64748B;text-transform:uppercase;"
        "letter-spacing:0.08em;margin-bottom:8px;'>Changed since last refresh</div>"
        + "".join(pills) +
        "</div>"
    )


# =============================================================================
# Helpers
# =============================================================================

def rating_html(rating):
    """Return HTML for rating pill. Falls back to a muted dash when no rating."""
    if not rating:
        return (
            '<span class="rating-pill" style="background:#F1F5F9;color:#94A3B8;'
            'font-weight:600;">—</span>'
        )
    cls = {"buy":"rating-buy", "hold":"rating-hold", "sell":"rating-sell"}.get(rating.lower(), "rating-hold")
    return f'<span class="rating-pill {cls}">{rating.upper()}</span>'

def pct_color(v):
    """Return color for percentage value."""
    if v > 0.05:  return "#00C896"
    if v < -0.05: return "#EF4444"
    return "#64748B"

def fmt_signed_pct(v, digits=2):
    """Format percentage with sign."""
    s = f"{v:.{digits}f}"
    return ("+" + s if v > 0 else s) + "%"


def fmt_money(v, digits=0):
    """Format GBP amount with thousands separator and sign."""
    sign = "+" if v > 0 else ("−" if v < 0 else "")
    return f"{sign}£{abs(v):,.{digits}f}"


def position_pnl(ticker):
    """
    Returns (current_value, cost_basis, pnl_abs, pnl_pct) or None if cost
    basis isn't set or the price data is missing.
    """
    info = st.session_state.etfs.get(ticker) or {}
    avg = info.get("avg_price")
    units = info.get("units")
    pd_ = st.session_state.price_data.get(ticker)
    if avg is None or units is None or not pd_:
        return None
    current = pd_.get("current")
    if not current:
        return None
    cost = float(avg) * float(units)
    value = float(current) * float(units)
    pnl_abs = value - cost
    pnl_pct = (current / avg - 1.0) * 100.0 if avg else 0.0
    return value, cost, pnl_abs, pnl_pct


def portfolio_pnl():
    """Sum (current_value, cost_basis, pnl_abs, pnl_pct_weighted) across all
    ETFs with holdings entered, or None if no holdings exist."""
    total_value = 0.0
    total_cost = 0.0
    any_held = False
    for t in st.session_state.etfs:
        p = position_pnl(t)
        if p is None:
            continue
        any_held = True
        value, cost, _, _ = p
        total_value += value
        total_cost += cost
    if not any_held or total_cost <= 0:
        return None
    pnl_abs = total_value - total_cost
    pnl_pct = (total_value / total_cost - 1.0) * 100.0
    return total_value, total_cost, pnl_abs, pnl_pct


# =============================================================================
# Time frame, sparkline, watchlist helpers
# =============================================================================

TIMEFRAMES = ["1W", "1M", "3M", "6M", "1Y", "YTD", "MAX"]
_TF_DAYS = {"1W": 5, "1M": 22, "3M": 66, "6M": 132, "1Y": 252}


def slice_history(history_df, tf):
    """Return the tail of history_df matching the time frame label."""
    if history_df is None or history_df.empty:
        return history_df
    if tf == "MAX":
        return history_df
    if tf == "YTD":
        cutoff = pd.Timestamp(_date.today().year, 1, 1)
        dates = pd.to_datetime(history_df["date"])
        return history_df.loc[dates >= cutoff]
    n = _TF_DAYS.get(tf, 66)
    return history_df.tail(n)


def return_over_window(history_df, tf):
    """% return over the chosen time frame, computed from the close column. None if not enough data."""
    sliced = slice_history(history_df, tf)
    if sliced is None or len(sliced) < 2:
        return None
    start = float(sliced["price"].iloc[0])
    end   = float(sliced["price"].iloc[-1])
    if start <= 0:
        return None
    return (end / start - 1.0) * 100.0


def timeframe_selector(key, default="3M"):
    """Render the standard time frame segmented control. Returns the chosen label."""
    chosen = st.segmented_control(
        "Time frame", options=TIMEFRAMES,
        default=st.session_state.get(key, default),
        key=key, label_visibility="collapsed",
    )
    return chosen or default


def render_sparkline(prices, avg_price=None, width=180, height=44):
    """Lightweight inline-SVG sparkline. Optional dashed avg-price overlay.

    Color: green if last > entry (or last > first when no avg_price), red otherwise.
    Returns an HTML string suitable for st.markdown(..., unsafe_allow_html=True).
    """
    arr = np.asarray([float(p) for p in prices if p == p], dtype=float)
    if len(arr) < 2:
        return ""
    mn, mx = float(arr.min()), float(arr.max())
    if avg_price:
        mn = min(mn, float(avg_price))
        mx = max(mx, float(avg_price))
    if mx == mn:
        mx = mn + 1.0
    ys = height - (arr - mn) / (mx - mn) * height
    xs = np.linspace(0, width, len(arr))
    pts = " ".join(f"{x:.1f},{y:.1f}" for x, y in zip(xs, ys))
    last = float(arr[-1])
    if avg_price:
        up = last > float(avg_price)
    else:
        up = last > float(arr[0])
    stroke = "#00C896" if up else "#EF4444"
    fill   = "rgba(0,200,150,0.10)" if up else "rgba(239,68,68,0.10)"
    parts = [
        f'<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}" '
        f'xmlns="http://www.w3.org/2000/svg" preserveAspectRatio="none" style="display:block;">',
        f'<polygon points="0,{height} {pts} {width},{height}" fill="{fill}" />',
        f'<polyline points="{pts}" fill="none" stroke="{stroke}" stroke-width="1.5" '
        f'stroke-linejoin="round" stroke-linecap="round" />',
    ]
    if avg_price:
        y_avg = height - (float(avg_price) - mn) / (mx - mn) * height
        parts.append(
            f'<line x1="0" y1="{y_avg:.1f}" x2="{width}" y2="{y_avg:.1f}" '
            f'stroke="#3B82F6" stroke-width="1" stroke-dasharray="3,3" opacity="0.75"/>'
        )
    parts.append("</svg>")
    return "".join(parts)


# Visual taxonomy for callouts
CALLOUT_RED   = ("#EF4444", "#FEF2F2")
CALLOUT_AMBER = ("#F59E0B", "#FEF3C7")
CALLOUT_GREEN = ("#00C896", "#E8FAF4")


def compute_callouts(ticker):
    """Return (negative_tags, positive_tags) — lists of (label, severity, fg, bg)."""
    pd_  = st.session_state.price_data.get(ticker) or {}
    flags = (st.session_state.signals_data.get(ticker) or {}).get("flags", {})
    score = (st.session_state.signals_data.get(ticker) or {}).get("score", 50.0)
    pnl   = position_pnl(ticker)

    neg, pos = [], []
    if pnl is not None:
        _, _, _, pnl_pct = pnl
        if pnl_pct < -5:
            neg.append(("big loss", f"{fmt_signed_pct(pnl_pct, 1)}", *CALLOUT_RED))
        elif pnl_pct > 10:
            pos.append(("big win", f"{fmt_signed_pct(pnl_pct, 1)}", *CALLOUT_GREEN))

    if flags.get("deep_drawdown"):
        dd = pd_.get("drawdown")
        sub = f"{dd:+.1f}%" if dd is not None else ""
        neg.append(("deep drawdown", sub, *CALLOUT_RED))
    if flags.get("death_cross"):
        neg.append(("death cross", "50/200 SMA", *CALLOUT_RED))

    if flags.get("high_vol"):
        v = pd_.get("vol_30d")
        sub = f"{v:.1f}%" if v is not None else ""
        neg.append(("high vol", sub, *CALLOUT_AMBER))
    if flags.get("rsi_overbought"):
        neg.append(("overbought", "RSI>70", *CALLOUT_AMBER))

    if score < 35:
        neg.append(("low score", f"{score:.0f}", *CALLOUT_AMBER))

    if flags.get("golden_cross"):
        pos.append(("golden cross", "50/200 SMA", *CALLOUT_GREEN))
    if flags.get("near_52w_high") and flags.get("momentum_1m_pos"):
        pos.append(("hot streak", "near 52w high", *CALLOUT_GREEN))
    if flags.get("rsi_oversold"):
        pos.append(("oversold dip", "RSI<30", *CALLOUT_GREEN))

    return neg, pos


def score_band_color(score):
    """Return the colored-border color for a card based on composite score."""
    if score >= 70:
        return "#00C896"
    if score < 35:
        return "#EF4444"
    return None  # default border


# =============================================================================
# Popover (re-uses helpers above)
# =============================================================================

def _render_etf_edit_popover(ticker, info):
    """Inline popover UI for category, cost basis, and re-verifying the Yahoo symbol."""
    st.caption("Category")
    new_cat = st.radio(
        "Category", ["Core", "Satellite"],
        index=0 if info["cat"] == "Core" else 1,
        horizontal=True, label_visibility="collapsed",
        key=f"cat_{ticker}",
    )
    if new_cat != info["cat"]:
        st.session_state.etfs[ticker]["cat"] = new_cat
        st.rerun()

    st.caption("Holdings")
    _avg = info.get("avg_price")
    _units = info.get("units")
    if _avg and _units:
        st.markdown(
            f"<span class='mono' style='font-size:12px;'>{_units:.0f} × £{_avg:,.2f}</span>",
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            "<span style='color:#94A3B8;font-size:11px;'>None set.</span>",
            unsafe_allow_html=True,
        )
    st.caption("Edit all holdings in bulk via the Overview tab.")

    st.caption("Yahoo symbol")
    st.markdown(
        f"<span class='mono' style='font-size:12px;'>"
        f"Currently <b>{info['yahoo']}</b></span>",
        unsafe_allow_html=True,
    )
    q = st.text_input(
        "Re-verify ticker", value=ticker,
        label_visibility="collapsed",
        key=f"verify_q_{ticker}",
    )
    if q and len(q.strip()) >= 2:
        with st.spinner("Searching…"):
            results = search_tickers(q.strip())
        if results:
            idx = st.selectbox(
                "Match", options=range(len(results)),
                format_func=lambda i: (
                    f"{results[i]['symbol']} — {results[i]['name']}"
                    + (f" ({results[i]['exchange']})" if results[i].get("exchange") else "")
                ),
                label_visibility="collapsed",
                key=f"verify_sel_{ticker}",
            )
            sel = results[idx]
            if st.button("Save changes", key=f"verify_save_{ticker}", use_container_width=True):
                st.session_state.etfs[ticker]["yahoo"] = sel["symbol"]
                st.session_state.etfs[ticker]["name"] = sel["name"]
                st.session_state.price_data.pop(ticker, None)
                st.session_state.signals_data.pop(ticker, None)
                st.rerun()
        else:
            st.warning("No results.")


@st.cache_data(ttl=300)
def search_tickers(query: str):
    """Search Yahoo Finance for tickers/names. Returns list of dicts with symbol/name/exchange/type."""
    try:
        results = yf.Search(query, max_results=8, enable_fuzzy_query=True, news_count=0)
        return [
            {
                "symbol": q["symbol"],
                "name": q.get("longname") or q.get("shortname", q["symbol"]),
                "exchange": q.get("exchDisp", ""),
                "type": q.get("quoteType", ""),
            }
            for q in results.quotes
            if q.get("isYahooFinance", False)
        ]
    except Exception:
        return []


# =============================================================================
# Sidebar
# =============================================================================

with st.sidebar:
    st.markdown("## Portfolio")
    st.caption(f"{len(st.session_state.etfs)} ETFs · GBP")

    # ---- allocations
    st.caption("Allocation")
    total = sum(st.session_state.allocs.values())
    total_color = "#0F172A" if abs(total - 100) < 0.01 else "#F59E0B"
    st.markdown(
        f"<div class='mono' style='font-size:15px;font-weight:600;color:{total_color};'>"
        f"{total:.1f}% <span style='color:#94A3B8;font-weight:400;font-size:13px;'>/ 100%</span>"
        f"</div>",
        unsafe_allow_html=True,
    )

    # group by category for sleeker editing
    _core_tickers = [t for t, v in st.session_state.etfs.items() if v["cat"] == "Core"]
    _sat_tickers  = [t for t, v in st.session_state.etfs.items() if v["cat"] == "Satellite"]
    _core_pct = sum(st.session_state.allocs.get(t, 0) for t in _core_tickers)
    _sat_pct  = sum(st.session_state.allocs.get(t, 0) for t in _sat_tickers)

    if _core_tickers:
        st.caption(f"Core · {_core_pct:.0f}%")
        for ticker in _core_tickers:
            st.session_state.allocs[ticker] = st.number_input(
                ticker,
                min_value=0.0, max_value=60.0, step=0.5,
                value=float(st.session_state.allocs.get(ticker, 0.0)),
                key=f"alloc_{ticker}",
            )

    if _sat_tickers:
        st.caption(f"Satellite · {_sat_pct:.0f}%")
        for ticker in _sat_tickers:
            st.session_state.allocs[ticker] = st.number_input(
                ticker,
                min_value=0.0, max_value=60.0, step=0.5,
                value=float(st.session_state.allocs.get(ticker, 0.0)),
                key=f"alloc_{ticker}",
            )

    # ---- universe (add / remove)
    st.caption("Universe")
    with st.expander("Manage ETFs", expanded=False):
        search_query = st.text_input(
            "Search ticker or name",
            placeholder="e.g. VWRP, Vanguard, iShares",
            label_visibility="collapsed",
            key="ticker_search_query",
        )
        if search_query and len(search_query.strip()) >= 2:
            with st.spinner("Searching…"):
                _results = search_tickers(search_query.strip())
            if _results:
                _selected_idx = st.selectbox(
                    "Select",
                    options=range(len(_results)),
                    format_func=lambda i: (
                        f"{_results[i]['symbol']} — {_results[i]['name']}"
                        + (f" ({_results[i]['exchange']})" if _results[i].get("exchange") else "")
                    ),
                    label_visibility="collapsed",
                    key="ticker_search_select",
                )
                _sel = _results[_selected_idx]
                st.caption(f"{_sel['name']} · {_sel.get('exchange', '')} · {_sel.get('type', '').lower()}")
                if st.button("Add to portfolio", use_container_width=True, key="ticker_add_btn"):
                    _yahoo = _sel["symbol"]
                    _base = _yahoo.split(".")[0]
                    if _base not in st.session_state.etfs:
                        st.session_state.etfs[_base] = {
                            "name": _sel["name"],
                            "yahoo": _yahoo,
                            "cat": "Satellite",
                        }
                        st.session_state.allocs[_base] = 0.0
                        st.rerun()
                    else:
                        st.warning(f"{_base} is already in your portfolio.")
            else:
                st.warning("No results — try a different term.")

        st.caption("Your ETFs")
        for ticker in list(st.session_state.etfs.keys()):
            _info = st.session_state.etfs[ticker]
            rc1, rc2, rc3 = st.columns([1.3, 1.4, 0.5])
            rc1.markdown(
                f"<div style='padding-top:8px;'>"
                f"<span class='mono' style='font-size:12px;font-weight:600;'>{ticker}</span>"
                f"<span style='font-size:10px;color:#94A3B8;margin-left:6px;'>{_info['cat'][:3].upper()}</span>"
                f"</div>",
                unsafe_allow_html=True,
            )
            with rc2.popover("Edit", use_container_width=True):
                _render_etf_edit_popover(ticker, _info)
            if rc3.button("✕", key=f"rm_{ticker}", help=f"Remove {ticker}"):
                del st.session_state.etfs[ticker]
                st.session_state.allocs.pop(ticker, None)
                st.rerun()

    # ---- usage + actions
    hrs = hours_since_last_fetch()
    next_refresh = max(0, API_MIN_REFRESH_HRS - (int(hrs) if hrs else 0))
    st.caption(f"Usage · ${st.session_state.api_spend:.3f} today · next refresh {next_refresh}h")

    st.divider()

    force = st.toggle("Force refresh (override throttle)", value=False, key="force_refresh")

    if st.button("↻ Refresh prices", use_container_width=True):
        with st.spinner("Fetching prices…"):
            etf_pairs = tuple((t, v["yahoo"]) for t, v in st.session_state.etfs.items())
            st.session_state.price_data = fetch_price_data(etf_pairs)
            st.session_state.signals_data = build_signals_for_all(
                st.session_state.price_data, st.session_state.news_data)
            persist_snapshots(st.session_state.etfs, st.session_state.price_data,
                              st.session_state.news_data, st.session_state.signals_data)
            st.session_state.changes = db.diff_vs_previous()
        st.toast("Prices refreshed ✓", icon="✅")

    if st.button("📰 Refresh news", use_container_width=True):
        hrs = hours_since_last_fetch()
        can_refresh = force or (hrs is None or hrs >= API_MIN_REFRESH_HRS)
        if not can_refresh:
            remaining = API_MIN_REFRESH_HRS - hours_since_last_fetch()
            st.warning(f"Throttled — next refresh in {remaining:.1f}h. Toggle 'Force refresh' to override.")
        else:
            with st.spinner("Fetching news…"):
                try:
                    st.session_state.news_data = fetch_news_and_ratings(st.session_state.etfs)
                    st.session_state.last_news_fetch = datetime.now()
                    st.session_state.api_spend += API_COST_PER_NEWS
                    st.session_state.signals_data = build_signals_for_all(
                        st.session_state.price_data, st.session_state.news_data)
                    persist_snapshots(st.session_state.etfs, st.session_state.price_data,
                                      st.session_state.news_data, st.session_state.signals_data)
                    st.session_state.changes = db.diff_vs_previous()
                    st.toast("News refreshed ✓", icon="✅")
                except Exception as e:
                    st.error(f"News fetch failed: {e}")

    if st.button("✨ Analyse portfolio", type="primary", use_container_width=True):
        with st.spinner("Generating analysis…"):
            try:
                st.session_state.analysis = generate_analysis(
                    st.session_state.allocs, st.session_state.news_data,
                    st.session_state.price_data, st.session_state.etfs)
                st.session_state.api_spend += API_COST_PER_ANALYSIS
                st.toast("Analysis generated ✓", icon="✨")
            except Exception as e:
                st.error(f"Analysis failed: {e}")

# =============================================================================
# Header
# =============================================================================

st.markdown("# ETF Tracker")

# =============================================================================
# Auto-fetch prices on first load
# =============================================================================

def _has_ohlc(pd_dict):
    """True only when the history df has the new shape with open/high/low columns."""
    if not pd_dict:
        return True  # nothing to check; treat as fresh
    for v in pd_dict.values():
        if not v:
            continue
        h = v.get("history")
        if h is None or h.empty:
            continue
        return {"open", "high", "low"}.issubset(set(h.columns))
    return True

# Force a re-fetch when the cached payload predates the OHLC schema change
if st.session_state.price_data and not _has_ohlc(st.session_state.price_data):
    st.cache_data.clear()
    st.session_state.price_data = {}
    st.session_state.signals_data = {}

if not st.session_state.price_data:
    with st.spinner("Fetching prices…"):
        etf_pairs = tuple((t, v["yahoo"]) for t, v in st.session_state.etfs.items())
        st.session_state.price_data = fetch_price_data(etf_pairs)
        st.session_state.signals_data = build_signals_for_all(
            st.session_state.price_data, st.session_state.news_data)
        persist_snapshots(st.session_state.etfs, st.session_state.price_data,
                          st.session_state.news_data, st.session_state.signals_data)
        st.session_state.changes = db.diff_vs_previous()
elif not st.session_state.signals_data:
    # Price data exists but signals haven't been computed yet (e.g. after rerun)
    st.session_state.signals_data = build_signals_for_all(
        st.session_state.price_data, st.session_state.news_data)

st.markdown("<div style='margin-bottom:8px;'></div>", unsafe_allow_html=True)

# =============================================================================
# Tabs
# =============================================================================

tab_over, tab_perf, tab_deep, tab_ai = st.tabs(
    ["Overview", "Performance", "Deep dive", "Insights"]
)

# ----------------------------------------------------------------------------- Overview
with tab_over:
    # ---- Time frame selector (drives hero metrics + sparklines)
    _tf_over = timeframe_selector("tf_overview", default="3M")

    # ---- Hero KPI strip
    _port_pnl = portfolio_pnl()

    def _kpi_tile(label, value_html, sub_html="", accent_color="#0F172A"):
        return (
            f"<div style='background:#FFFFFF;border:1px solid #E5E7EB;border-radius:10px;"
            f"padding:14px 16px;height:100%;'>"
            f"<div style='font-size:11px;font-weight:600;color:#64748B;text-transform:uppercase;"
            f"letter-spacing:0.08em;'>{label}</div>"
            f"<div class='mono' style='font-size:22px;font-weight:600;color:{accent_color};"
            f"letter-spacing:-0.02em;margin-top:4px;'>{value_html}</div>"
            f"<div style='font-size:11px;color:#94A3B8;margin-top:2px;'>{sub_html}</div>"
            f"</div>"
        )

    # Compute per-ETF return-over-window once, reused for ranking + tile sub
    _tf_returns = {}
    for _t, _pd_ in st.session_state.price_data.items():
        if not _pd_:
            continue
        _h = _pd_.get("history")
        if _h is None or _h.empty:
            continue
        _r = return_over_window(_h, _tf_over)
        if _r is not None:
            _tf_returns[_t] = _r

    if _port_pnl:
        _value, _cost, _pnl_abs, _pnl_pct = _port_pnl
        _pnl_color = pct_color(_pnl_pct)
        # Top/bottom by P/L %
        _held_pnls = []
        for _t in st.session_state.etfs:
            _pp = position_pnl(_t)
            if _pp:
                _held_pnls.append((_t, _pp[3]))
        _held_pnls.sort(key=lambda x: x[1], reverse=True)
        _best = _held_pnls[0]  if _held_pnls else None
        _worst = _held_pnls[-1] if len(_held_pnls) > 1 else None
        _best_html = (
            f"{_best[0]} <span style='font-size:13px;color:{pct_color(_best[1])};'>"
            f"{fmt_signed_pct(_best[1], 1)}</span>"
        ) if _best else "—"
        _worst_html = (
            f"{_worst[0]} <span style='font-size:13px;color:{pct_color(_worst[1])};'>"
            f"{fmt_signed_pct(_worst[1], 1)}</span>"
        ) if _worst else "—"

        kc1, kc2, kc3, kc4 = st.columns(4)
        kc1.markdown(_kpi_tile("Portfolio value", f"£{_value:,.0f}",
                               f"{len(_held_pnls)} positions held"),
                     unsafe_allow_html=True)
        kc2.markdown(_kpi_tile("Unrealised P/L", fmt_money(_pnl_abs),
                               fmt_signed_pct(_pnl_pct, 2),
                               accent_color=_pnl_color),
                     unsafe_allow_html=True)
        kc3.markdown(_kpi_tile("Top performer", _best_html,
                               f"by P/L %"),
                     unsafe_allow_html=True)
        kc4.markdown(_kpi_tile("Biggest drag", _worst_html,
                               f"by P/L %"),
                     unsafe_allow_html=True)
    else:
        # Fallback tiles when no holdings entered yet
        _n = len(st.session_state.etfs)
        _wtd = sum(
            (st.session_state.allocs.get(t, 0) / 100.0) * (r or 0)
            for t, r in _tf_returns.items()
        )
        _best = max(_tf_returns.items(), key=lambda kv: kv[1]) if _tf_returns else None
        _worst = min(_tf_returns.items(), key=lambda kv: kv[1]) if _tf_returns else None
        _best_html = (
            f"{_best[0]} <span style='font-size:13px;color:{pct_color(_best[1])};'>"
            f"{fmt_signed_pct(_best[1], 1)}</span>"
        ) if _best else "—"
        _worst_html = (
            f"{_worst[0]} <span style='font-size:13px;color:{pct_color(_worst[1])};'>"
            f"{fmt_signed_pct(_worst[1], 1)}</span>"
        ) if _worst else "—"
        _core_n = sum(1 for v in st.session_state.etfs.values() if v["cat"] == "Core")
        _sat_n  = _n - _core_n

        kc1, kc2, kc3, kc4 = st.columns(4)
        kc1.markdown(_kpi_tile("Positions", f"{_n}",
                               f"{_core_n} Core · {_sat_n} Satellite"),
                     unsafe_allow_html=True)
        kc2.markdown(_kpi_tile(f"Weighted {_tf_over}",
                               fmt_signed_pct(_wtd, 1),
                               "allocation × return",
                               accent_color=pct_color(_wtd)),
                     unsafe_allow_html=True)
        kc3.markdown(_kpi_tile(f"Top mover ({_tf_over})", _best_html, ""),
                     unsafe_allow_html=True)
        kc4.markdown(_kpi_tile(f"Worst mover ({_tf_over})", _worst_html, ""),
                     unsafe_allow_html=True)

    # ---- Wide portfolio-value sparkline (only when holdings exist)
    if _port_pnl:
        _value_frames = {}
        _total_cost_basis = 0.0
        for _t in st.session_state.etfs:
            _meta = st.session_state.etfs.get(_t) or {}
            _avg_p = _meta.get("avg_price")
            _u = _meta.get("units")
            _pd_ = st.session_state.price_data.get(_t)
            if not (_avg_p and _u and _pd_):
                continue
            _h = _pd_.get("history")
            if _h is None or _h.empty:
                continue
            _s = _h.set_index(pd.to_datetime(_h["date"]))["price"].astype(float) * float(_u)
            _value_frames[_t] = _s
            _total_cost_basis += float(_avg_p) * float(_u)
        if _value_frames and _total_cost_basis > 0:
            _vdf = pd.DataFrame(_value_frames).sort_index().ffill().dropna(how="all")
            _vdf["total"] = _vdf.sum(axis=1)
            _spark_tail = slice_history(
                pd.DataFrame({"date": _vdf.index, "price": _vdf["total"].values}),
                _tf_over,
            )
            if len(_spark_tail) >= 2:
                st.markdown(
                    "<div style='margin-top:10px;'>"
                    f"<div style='font-size:11px;font-weight:600;color:#64748B;"
                    f"text-transform:uppercase;letter-spacing:0.08em;margin-bottom:4px;'>"
                    f"Portfolio value · {_tf_over}</div>"
                    + render_sparkline(_spark_tail["price"].values,
                                       avg_price=_total_cost_basis,
                                       width=1200, height=70)
                    + "</div>",
                    unsafe_allow_html=True,
                )

    # ---- Bulk holdings editor
    st.markdown("<div style='height:18px;'></div>", unsafe_allow_html=True)
    _any_holdings = any(
        v.get("avg_price") and v.get("units")
        for v in st.session_state.etfs.values()
    )
    with st.expander("Edit all holdings", expanded=not _any_holdings):
        _editor_rows = []
        for _t, _info in st.session_state.etfs.items():
            _curr = (st.session_state.price_data.get(_t) or {}).get("current")
            _avg_p = _info.get("avg_price") or 0.0
            _units = _info.get("units") or 0.0
            _cost = _avg_p * _units if (_avg_p and _units) else 0.0
            _val = (_curr or 0.0) * _units if _units else 0.0
            _pnl_abs = (_val - _cost) if _cost else 0.0
            _pnl_pct = ((_curr / _avg_p - 1) * 100) if (_curr and _avg_p) else 0.0
            _editor_rows.append({
                "Ticker": _t,
                "Name": _info.get("name", ""),
                "Avg price (£)": float(_avg_p),
                "Units": float(_units),
                "Cost basis": float(_cost),
                "Current value": float(_val),
                "P/L (£)": float(_pnl_abs),
                "P/L %": float(_pnl_pct),
            })
        _editor_df = pd.DataFrame(_editor_rows)

        _edited = st.data_editor(
            _editor_df,
            hide_index=True,
            use_container_width=True,
            num_rows="fixed",
            column_config={
                "Ticker": st.column_config.TextColumn("Ticker", disabled=True, width="small"),
                "Name":   st.column_config.TextColumn("Name", disabled=True),
                "Avg price (£)": st.column_config.NumberColumn(
                    "Avg price (£)", min_value=0.0, step=0.01, format="£%.2f"),
                "Units": st.column_config.NumberColumn(
                    "Units", min_value=0.0, step=1.0, format="%.0f"),
                "Cost basis": st.column_config.NumberColumn(
                    "Cost", disabled=True, format="£%,.0f"),
                "Current value": st.column_config.NumberColumn(
                    "Value", disabled=True, format="£%,.0f"),
                "P/L (£)": st.column_config.NumberColumn(
                    "P/L (£)", disabled=True, format="£%,.0f"),
                "P/L %": st.column_config.NumberColumn(
                    "P/L %", disabled=True, format="%+.2f%%"),
            },
            key="holdings_editor",
        )

        if st.button("Save all holdings", type="primary", key="bulk_save_holdings",
                     use_container_width=True):
            for _, _row in _edited.iterrows():
                _t = _row["Ticker"]
                _avg_p = float(_row["Avg price (£)"] or 0.0)
                _units = float(_row["Units"] or 0.0)
                if _avg_p > 0 and _units > 0:
                    st.session_state.etfs[_t]["avg_price"] = _avg_p
                    st.session_state.etfs[_t]["units"] = _units
                else:
                    st.session_state.etfs[_t].pop("avg_price", None)
                    st.session_state.etfs[_t].pop("units", None)
            save_holdings(st.session_state.etfs)
            st.toast("Holdings saved ✓", icon="✅")
            st.rerun()

    # ---- Watchlist / Good shape strip
    _neg_by_ticker, _pos_by_ticker = {}, {}
    for _t in st.session_state.etfs:
        _neg, _pos = compute_callouts(_t)
        if _neg:
            _neg_by_ticker[_t] = _neg
        if _pos:
            _pos_by_ticker[_t] = _pos

    def _render_pill_row(label, by_ticker):
        if not by_ticker:
            return
        pills = []
        for _t, _tags in by_ticker.items():
            for _name, _sub, _fg, _bg in _tags:
                sub_html = (
                    f"<span style='font-size:9px;color:{_fg};opacity:0.7;margin-left:4px;'>{_sub}</span>"
                    if _sub else ""
                )
                pills.append(
                    f"<span style='background:{_bg};color:{_fg};font-size:10px;font-weight:600;"
                    f"padding:4px 8px;border-radius:6px;margin:0 6px 6px 0;display:inline-block;"
                    f"white-space:nowrap;'>"
                    f"<span class='mono' style='font-weight:700;'>{_t}</span>"
                    f"<span style='margin:0 5px;color:{_fg};opacity:0.6;'>·</span>"
                    f"{_name}{sub_html}</span>"
                )
        st.markdown(
            f"<div style='margin-top:14px;'>"
            f"<div style='font-size:11px;font-weight:600;color:#64748B;"
            f"text-transform:uppercase;letter-spacing:0.08em;margin-bottom:6px;'>{label}</div>"
            f"<div>{''.join(pills)}</div>"
            f"</div>",
            unsafe_allow_html=True,
        )

    _render_pill_row("Needs attention", _neg_by_ticker)
    _render_pill_row("Good shape", _pos_by_ticker)

    # "What changed since last refresh" strip
    st.markdown("<div style='height:8px;'></div>", unsafe_allow_html=True)
    changes_html = render_changes_strip(st.session_state.changes)
    if changes_html:
        st.markdown(changes_html, unsafe_allow_html=True)

    core_etfs = {t: v for t, v in st.session_state.etfs.items() if v["cat"] == "Core"}
    sat_etfs = {t: v for t, v in st.session_state.etfs.items() if v["cat"] == "Satellite"}

    def _score_for(ticker):
        return (st.session_state.signals_data.get(ticker) or {}).get("score", 50.0)

    def render_etf_card(ticker):
        info = st.session_state.etfs[ticker]
        rating_data = st.session_state.news_data.get(ticker)
        rating = (rating_data or {}).get("rating", "")  # empty when news not fetched
        price_data = st.session_state.price_data.get(ticker)
        sig = st.session_state.signals_data.get(ticker) or {}
        flags = sig.get("flags", {})
        score = sig.get("score", 50.0)
        pnl = position_pnl(ticker)

        with st.container(border=True):
            # Score-band colored bar at top of card (only when score is in green/red band)
            _band_color = score_band_color(score)
            if _band_color:
                st.markdown(
                    f"<div style='height:3px;background:{_band_color};border-radius:2px;"
                    f"margin:-2px 0 8px 0;'></div>",
                    unsafe_allow_html=True,
                )

            top1, top2 = st.columns([3, 1])
            with top1:
                st.markdown(
                    f"<div style='font-family:JetBrains Mono,monospace;font-size:16px;font-weight:600;letter-spacing:-0.01em;'>{ticker}</div>"
                    f"<div style='font-size:12px;color:#64748B;margin-top:2px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;'>{info['name']}</div>",
                    unsafe_allow_html=True,
                )
            with top2:
                st.markdown(rating_html(rating), unsafe_allow_html=True)

            # score badge + signal chips row
            chips_html = render_signal_chips(flags)
            score_badge = (
                f"<span style='background:#E2E8F0;color:#475569;font-size:9px;font-weight:700;"
                f"padding:2px 5px;border-radius:3px;letter-spacing:0.04em;"
                f"margin-right:3px;display:inline-block;'>Score {score:.0f}</span>"
            )
            st.markdown(
                f"<div style='margin:6px 0 4px 0;line-height:1.8;'>{score_badge}{chips_html}</div>",
                unsafe_allow_html=True,
            )

            # ---- Sparkline: time-frame-windowed price with optional avg-price overlay
            if price_data and not price_data.get("history", pd.DataFrame()).empty:
                _h_card = slice_history(price_data["history"], _tf_over)
                if _h_card is not None and len(_h_card) >= 2:
                    _avg_for_spark = info.get("avg_price")
                    _spark_svg = render_sparkline(
                        _h_card["price"].values,
                        avg_price=_avg_for_spark,
                        width=320, height=46,
                    )
                    st.markdown(
                        f"<div style='margin:4px 0 8px 0;'>{_spark_svg}</div>",
                        unsafe_allow_html=True,
                    )

            mid1, mid2 = st.columns(2)
            with mid1:
                st.markdown(
                    f"<div class='mono' style='font-size:18px;font-weight:600;'>{st.session_state.allocs.get(ticker, 0):.1f}%</div>"
                    f"<div style='font-size:10px;color:#64748B;text-transform:uppercase;letter-spacing:0.1em;'>allocation</div>",
                    unsafe_allow_html=True,
                )
            with mid2:
                if price_data and not price_data.get("history", pd.DataFrame()).empty:
                    last_price = price_data["current"]
                    st.markdown(
                        f"<div class='mono' style='font-size:18px;font-weight:600;text-align:right;'>£{last_price:,.2f}</div>"
                        f"<div style='font-size:10px;color:#64748B;text-transform:uppercase;letter-spacing:0.1em;text-align:right;'>last close</div>",
                        unsafe_allow_html=True,
                    )

            rc1, rc2, rc3 = st.columns(3)
            for col, period in zip([rc1, rc2, rc3], ["ret_1w", "ret_1m", "ret_3m"]):
                v = price_data.get(period, 0) if price_data else 0
                period_label = period.replace("ret_", "").upper()
                with col:
                    st.markdown(
                        f"<div style='font-size:10px;color:#64748B;text-transform:uppercase;letter-spacing:0.1em;'>{period_label}</div>"
                        f"<div class='mono' style='font-size:13px;font-weight:600;color:{pct_color(v)};'>{fmt_signed_pct(v)}</div>",
                        unsafe_allow_html=True,
                    )

            # P&L row — only when holdings are set on this ticker
            if pnl:
                _value, _cost, _pnl_abs, _pnl_pct = pnl
                _c = pct_color(_pnl_pct)
                st.markdown(
                    f"<div style='margin-top:8px;padding-top:8px;border-top:1px solid #E5E7EB;"
                    f"display:flex;justify-content:space-between;align-items:baseline;'>"
                    f"<span style='font-size:10px;color:#64748B;text-transform:uppercase;letter-spacing:0.1em;'>P/L</span>"
                    f"<span class='mono' style='font-size:13px;font-weight:600;color:{_c};'>"
                    f"{fmt_money(_pnl_abs)} <span style='font-size:11px;font-weight:500;'>({fmt_signed_pct(_pnl_pct,1)})</span>"
                    f"</span>"
                    f"</div>",
                    unsafe_allow_html=True,
                )

    # --- core section
    core_pct = sum(st.session_state.allocs.get(t, 0) for t in core_etfs)
    sat_pct = sum(st.session_state.allocs.get(t, 0) for t in sat_etfs)

    head_c1, head_c2 = st.columns([4, 1])
    head_c1.caption(f"Core · {core_pct:.0f}%")
    head_c2.markdown("<div style='text-align:right;color:#64748B;font-size:12px;padding-top:2px;'>broad-market beta</div>", unsafe_allow_html=True)

    core_list = sorted(core_etfs.keys(), key=_score_for, reverse=True)
    for row_start in range(0, len(core_list), 3):
        cols = st.columns(3)
        for col, ticker in zip(cols, core_list[row_start:row_start + 3]):
            with col:
                render_etf_card(ticker)

    st.markdown("<div style='height:16px;'></div>", unsafe_allow_html=True)

    head_s1, head_s2 = st.columns([4, 1])
    head_s1.caption(f"Satellite · {sat_pct:.0f}%")
    head_s2.markdown("<div style='text-align:right;color:#64748B;font-size:12px;padding-top:2px;'>thematic overlay</div>", unsafe_allow_html=True)

    sat_list = sorted(sat_etfs.keys(), key=_score_for, reverse=True)
    for row_start in range(0, len(sat_list), 3):
        cols = st.columns(3)
        for col, ticker in zip(cols, sat_list[row_start:row_start + 3]):
            with col:
                render_etf_card(ticker)

# ----------------------------------------------------------------------------- Performance
with tab_perf:
    _tf_perf = timeframe_selector("tf_performance", default="3M")
    st.caption(f"Normalised price · {_tf_perf}, rebased to 100")

    all_tickers = list(st.session_state.etfs.keys())
    default_picks = [t for t in ["VWRP", "SPDR", "NATP", "NUCG", "RBTX"] if t in all_tickers]
    picks = st.multiselect(
        "Compare",
        options=all_tickers,
        default=default_picks,
        label_visibility="collapsed",
    )

    line_palette = ["#0F172A", "#00C896", "#F59E0B", "#3B82F6", "#8B5CF6", "#EF4444", "#06B6D4", "#EC4899"]
    fig = go.Figure()
    for i, t in enumerate(picks):
        price_info = st.session_state.price_data.get(t)
        if price_info and not price_info.get("history", pd.DataFrame()).empty:
            df = slice_history(price_info["history"], _tf_perf)
            if df is None or df.empty:
                continue
            base = df["price"].iloc[0]
            rebased = (df["price"] / base) * 100.0
            fig.add_trace(go.Scatter(
                x=df["date"], y=rebased,
                mode="lines", name=t,
                line=dict(color=line_palette[i % len(line_palette)], width=2),
                hovertemplate=f"<b>{t}</b><br>%{{x|%d %b}}<br>%{{y:.2f}}<extra></extra>",
            ))
    fig.add_hline(y=100, line_dash="dash", line_color="#94A3B8", line_width=1)
    fig.update_layout(
        height=440, margin=dict(l=40, r=20, t=20, b=40),
        paper_bgcolor="#FFFFFF", plot_bgcolor="#FFFFFF",
        font=dict(family="Helvetica Neue", size=12, color="#0F172A"),
        legend=dict(orientation="h", yanchor="bottom", y=1.0, xanchor="left", x=0, font=dict(size=11)),
        hovermode="x unified",
    )
    fig.update_xaxes(gridcolor="#E5E7EB", tickfont=dict(color="#64748B", size=11))
    fig.update_yaxes(gridcolor="#E5E7EB", tickfont=dict(color="#64748B", size=11))
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})

    st.markdown("<div style='height:24px;'></div>", unsafe_allow_html=True)

    # ---------- Risk / return scatter
    st.caption(f"Risk vs return · {_tf_perf} return × {_tf_perf} volatility")
    scatter_rows = []
    for t, info in st.session_state.etfs.items():
        pd_ = st.session_state.price_data.get(t)
        if not pd_: continue
        _h = pd_.get("history")
        _ret = return_over_window(_h, _tf_perf) if _h is not None else None
        _sl = slice_history(_h, _tf_perf) if _h is not None else None
        if _sl is not None and len(_sl) > 1:
            _vol = float(_sl["price"].pct_change().std() * (252 ** 0.5) * 100)
        else:
            _vol = pd_.get("vol_30d") or 0.0
        scatter_rows.append({
            "ticker": t,
            "ret": _ret if _ret is not None else 0.0,
            "vol": _vol,
            "allocation": st.session_state.allocs.get(t, 0.0),
            "rating": (st.session_state.news_data.get(t) or {}).get("rating", "hold").upper(),
        })
    if scatter_rows:
        sdf = pd.DataFrame(scatter_rows)
        rating_colors = {"BUY": "#00C896", "HOLD": "#F59E0B", "SELL": "#EF4444"}
        fig2 = px.scatter(
            sdf, x="ret", y="vol", size="allocation", color="rating",
            text="ticker", color_discrete_map=rating_colors,
            size_max=44, hover_data={"allocation": ":.1f"},
        )
        fig2.update_traces(textposition="top center", textfont=dict(size=10, color="#0F172A"))
        fig2.add_vline(x=0, line_dash="dash", line_color="#94A3B8", line_width=1)
        fig2.update_layout(
            height=420, margin=dict(l=40, r=20, t=20, b=40),
            paper_bgcolor="#FFFFFF", plot_bgcolor="#FFFFFF",
            font=dict(family="Helvetica Neue", size=12, color="#0F172A"),
            legend=dict(orientation="h", yanchor="bottom", y=1.0, xanchor="left", x=0, font=dict(size=11), title=None),
            xaxis_title=f"{_tf_perf} return (%)", yaxis_title=f"{_tf_perf} annualised volatility (%)",
        )
        fig2.update_xaxes(gridcolor="#E5E7EB", tickfont=dict(color="#64748B", size=11))
        fig2.update_yaxes(gridcolor="#E5E7EB", tickfont=dict(color="#64748B", size=11))
        st.plotly_chart(fig2, use_container_width=True, config={"displayModeBar": False})

    st.markdown("<div style='height:24px;'></div>", unsafe_allow_html=True)

    # ---------- Correlation heatmap (windowed daily returns)
    st.caption(f"Correlation · {_tf_perf} daily returns")
    ret_frames = {}
    for t in st.session_state.etfs:
        pd_ = st.session_state.price_data.get(t)
        if pd_ and not pd_.get("history", pd.DataFrame()).empty:
            h = slice_history(pd_["history"], _tf_perf)
            if h is None or h.empty:
                continue
            s = h.set_index("date")["price"].astype(float)
            ret_frames[t] = s.pct_change().dropna()
    if len(ret_frames) >= 2:
        corr_df = pd.DataFrame(ret_frames).corr()
        fig3 = px.imshow(
            corr_df, color_continuous_scale="RdBu_r", zmin=-1, zmax=1,
            aspect="auto", text_auto=".2f",
        )
        fig3.update_layout(
            height=460, margin=dict(l=20, r=20, t=20, b=20),
            paper_bgcolor="#FFFFFF", plot_bgcolor="#FFFFFF",
            font=dict(family="Helvetica Neue", size=11, color="#0F172A"),
            coloraxis_colorbar=dict(thickness=12, len=0.6),
        )
        fig3.update_xaxes(side="bottom", tickfont=dict(color="#64748B", size=10))
        fig3.update_yaxes(tickfont=dict(color="#64748B", size=10))
        st.plotly_chart(fig3, use_container_width=True, config={"displayModeBar": False})

    st.markdown("<div style='height:24px;'></div>", unsafe_allow_html=True)

    # ---------- Drawdown over time
    st.caption(f"Drawdown from running peak · {_tf_perf}")
    fig4 = go.Figure()
    plotted = 0
    for i, t in enumerate(picks):
        pd_ = st.session_state.price_data.get(t)
        if not pd_ or pd_.get("history", pd.DataFrame()).empty: continue
        h = slice_history(pd_["history"], _tf_perf)
        if h is None or h.empty:
            continue
        h = h.sort_values("date")
        price = h["price"].astype(float)
        peak = price.cummax()
        dd = (price / peak - 1) * 100
        fig4.add_trace(go.Scatter(
            x=h["date"], y=dd, mode="lines", name=t,
            line=dict(color=line_palette[i % len(line_palette)], width=1.6),
            hovertemplate=f"<b>{t}</b><br>%{{x|%d %b}}<br>%{{y:.2f}}%<extra></extra>",
        ))
        plotted += 1
    if plotted:
        fig4.add_hline(y=0, line_dash="dash", line_color="#94A3B8", line_width=1)
        fig4.update_layout(
            height=340, margin=dict(l=40, r=20, t=20, b=40),
            paper_bgcolor="#FFFFFF", plot_bgcolor="#FFFFFF",
            font=dict(family="Helvetica Neue", size=12, color="#0F172A"),
            legend=dict(orientation="h", yanchor="bottom", y=1.0, xanchor="left", x=0, font=dict(size=11)),
            hovermode="x unified",
        )
        fig4.update_xaxes(gridcolor="#E5E7EB", tickfont=dict(color="#64748B", size=11))
        fig4.update_yaxes(gridcolor="#E5E7EB", tickfont=dict(color="#64748B", size=11),
                          ticksuffix="%", zeroline=False)
        st.plotly_chart(fig4, use_container_width=True, config={"displayModeBar": False})

    # ===================================================================
    # Cost-basis-aware portfolio views
    # ===================================================================
    _held = [(t, position_pnl(t)) for t in st.session_state.etfs]
    _held = [(t, p) for t, p in _held if p is not None]

    if not _held:
        st.markdown("<div style='height:32px;'></div>", unsafe_allow_html=True)
        st.info(
            "Enter average purchase price + units on at least one ETF "
            "(via the **Manage ETFs** popover in the sidebar) to unlock "
            "P/L ranking, allocation drift, and portfolio value over time."
        )
    else:
        # ---------- P&L ranking bar chart
        st.markdown("<div style='height:32px;'></div>", unsafe_allow_html=True)
        st.caption("P/L ranking · winners and losers")
        _pnl_rows = []
        for t, (_value, _cost, _pnl_abs, _pnl_pct) in _held:
            _pnl_rows.append({
                "ticker": t,
                "pnl_abs": _pnl_abs,
                "pnl_pct": _pnl_pct,
                "color": "#00C896" if _pnl_abs >= 0 else "#EF4444",
            })
        _pdf = pd.DataFrame(_pnl_rows).sort_values("pnl_abs", ascending=True)
        fig_r = go.Figure(go.Bar(
            x=_pdf["pnl_abs"], y=_pdf["ticker"],
            orientation="h",
            marker_color=_pdf["color"].tolist(),
            text=[f"{fmt_money(v, 0)}  ({fmt_signed_pct(p, 1)})"
                  for v, p in zip(_pdf["pnl_abs"], _pdf["pnl_pct"])],
            textposition="outside",
            textfont=dict(size=11, color="#0F172A"),
            hovertemplate="<b>%{y}</b><br>P/L %{x:,.2f}<extra></extra>",
        ))
        fig_r.add_vline(x=0, line_color="#94A3B8", line_width=1)
        fig_r.update_layout(
            height=max(220, 36 * len(_pdf) + 80),
            margin=dict(l=60, r=120, t=10, b=30),
            paper_bgcolor="#FFFFFF", plot_bgcolor="#FFFFFF",
            font=dict(family="Helvetica Neue", size=12, color="#0F172A"),
            showlegend=False,
        )
        fig_r.update_xaxes(gridcolor="#E5E7EB", tickfont=dict(color="#64748B", size=11),
                           tickprefix="£", zeroline=False)
        fig_r.update_yaxes(tickfont=dict(color="#0F172A", size=12,
                                         family="JetBrains Mono, monospace"))
        st.plotly_chart(fig_r, use_container_width=True, config={"displayModeBar": False})

        # ---------- Allocation drift: target vs current value-weighted
        st.markdown("<div style='height:24px;'></div>", unsafe_allow_html=True)
        st.caption("Allocation drift · target vs current value-weighted")
        _total_value = sum(p[0] for _t, p in _held)
        _drift_rows = []
        for t, (_value, _cost, _pnl_abs, _pnl_pct) in _held:
            _drift_rows.append({
                "ticker": t,
                "target": st.session_state.allocs.get(t, 0.0),
                "current": (_value / _total_value * 100.0) if _total_value else 0.0,
            })
        _ddf = pd.DataFrame(_drift_rows).sort_values("target", ascending=False)
        fig_a = go.Figure()
        fig_a.add_trace(go.Bar(
            name="Target %", x=_ddf["ticker"], y=_ddf["target"],
            marker_color="#CBD5E1",
            hovertemplate="<b>%{x}</b><br>Target %{y:.1f}%<extra></extra>",
        ))
        fig_a.add_trace(go.Bar(
            name="Current %", x=_ddf["ticker"], y=_ddf["current"],
            marker_color="#0F172A",
            hovertemplate="<b>%{x}</b><br>Current %{y:.1f}%<extra></extra>",
        ))
        fig_a.update_layout(
            barmode="group", bargap=0.25, bargroupgap=0.08,
            height=320, margin=dict(l=40, r=20, t=10, b=40),
            paper_bgcolor="#FFFFFF", plot_bgcolor="#FFFFFF",
            font=dict(family="Helvetica Neue", size=12, color="#0F172A"),
            legend=dict(orientation="h", yanchor="bottom", y=1.0, xanchor="left", x=0, font=dict(size=11)),
        )
        fig_a.update_xaxes(tickfont=dict(color="#64748B", size=11,
                                        family="JetBrains Mono, monospace"))
        fig_a.update_yaxes(gridcolor="#E5E7EB", tickfont=dict(color="#64748B", size=11),
                           ticksuffix="%", zeroline=False)
        st.plotly_chart(fig_a, use_container_width=True, config={"displayModeBar": False})

        # ---------- Portfolio value over time
        st.markdown("<div style='height:24px;'></div>", unsafe_allow_html=True)
        st.caption("Portfolio value over time · assuming current units held")

        # Align history series across all held tickers, multiply by units, sum.
        _value_frames = {}
        _total_cost_basis = 0.0
        for t, _ in _held:
            _pd = st.session_state.price_data.get(t)
            _meta = st.session_state.etfs.get(t) or {}
            _units = _meta.get("units")
            _avg = _meta.get("avg_price")
            if not _pd or _units is None or _avg is None:
                continue
            _h = _pd.get("history")
            if _h is None or _h.empty:
                continue
            _s = _h.set_index(pd.to_datetime(_h["date"]))["price"].astype(float) * float(_units)
            _value_frames[t] = _s
            _total_cost_basis += float(_avg) * float(_units)

        if _value_frames and _total_cost_basis > 0:
            _vdf = pd.DataFrame(_value_frames).sort_index().ffill().dropna(how="all")
            _vdf["total"] = _vdf.sum(axis=1)
            _vdf_sliced = slice_history(
                pd.DataFrame({"date": _vdf.index, "price": _vdf["total"].values}),
                _tf_perf,
            )
            if _vdf_sliced is not None and not _vdf_sliced.empty:
                _vdf = _vdf_sliced.set_index("date")
                _vdf["total"] = _vdf["price"]
            fig_pv = go.Figure()
            fig_pv.add_trace(go.Scatter(
                x=_vdf.index, y=_vdf["total"], mode="lines",
                line=dict(color="#0F172A", width=2),
                fill="tozeroy", fillcolor="rgba(15,23,42,0.05)",
                name="Portfolio value",
                hovertemplate="%{x|%d %b %Y}<br>£%{y:,.0f}<extra></extra>",
            ))
            fig_pv.add_hline(
                y=_total_cost_basis,
                line_dash="dash", line_color="#3B82F6", line_width=1.5,
                annotation_text=f"Cost basis £{_total_cost_basis:,.0f}",
                annotation_position="top left",
                annotation_font=dict(size=10, color="#3B82F6"),
            )
            fig_pv.update_layout(
                height=360, margin=dict(l=50, r=20, t=10, b=40),
                paper_bgcolor="#FFFFFF", plot_bgcolor="#FFFFFF",
                font=dict(family="Helvetica Neue", size=12, color="#0F172A"),
                showlegend=False,
            )
            fig_pv.update_xaxes(gridcolor="#E5E7EB", tickfont=dict(color="#64748B", size=11))
            fig_pv.update_yaxes(gridcolor="#E5E7EB", tickfont=dict(color="#64748B", size=11),
                                tickprefix="£", zeroline=False)
            st.plotly_chart(fig_pv, use_container_width=True, config={"displayModeBar": False})
            st.caption(
                f"Assumes you held {sum(1 for _ in _value_frames)} positions "
                "with current unit counts throughout — historical reconstruction, "
                "not actual past portfolio. Useful for break-even visualisation."
            )

# ----------------------------------------------------------------------------- Deep dive
with tab_deep:
    _tickers = list(st.session_state.etfs.keys())
    if not _tickers:
        st.info("Add an ETF in the sidebar to see its deep-dive view.")
    else:
        _dc1, _dc2 = st.columns([3, 2])
        with _dc1:
            _pick = st.selectbox(
                "ETF",
                options=_tickers,
                format_func=lambda t: f"{t} — {st.session_state.etfs[t]['name']}",
                key="deep_pick",
                label_visibility="collapsed",
            )
        with _dc2:
            _tf_deep = timeframe_selector("tf_deep", default="6M")
        _info = st.session_state.etfs[_pick]
        _pd = st.session_state.price_data.get(_pick)

        if not _pd or _pd.get("history", pd.DataFrame()).empty:
            st.warning(
                f"No price data for {_pick}. Click ↻ Refresh prices in the sidebar."
            )
        else:
            _hist_full = _pd["history"].copy()
            _hist_full["date"] = pd.to_datetime(_hist_full["date"])
            _hist_full = _hist_full.sort_values("date").reset_index(drop=True)
            _hist = slice_history(_hist_full, _tf_deep)
            if _hist is None or _hist.empty:
                _hist = _hist_full

            # ----- key stats cards
            kc1, kc2, kc3, kc4 = st.columns(4)
            with kc1:
                st.markdown(
                    f"<div style='font-size:10px;color:#64748B;text-transform:uppercase;letter-spacing:0.1em;'>Current</div>"
                    f"<div class='mono' style='font-size:20px;font-weight:600;'>£{_pd['current']:,.2f}</div>",
                    unsafe_allow_html=True,
                )
            with kc2:
                if _pd.get("high_52w") and _pd.get("low_52w"):
                    _lo, _hi = _pd["low_52w"], _pd["high_52w"]
                    _pos = (_pd["current"] - _lo) / (_hi - _lo) * 100 if _hi > _lo else 50
                    st.markdown(
                        f"<div style='font-size:10px;color:#64748B;text-transform:uppercase;letter-spacing:0.1em;'>52w range</div>"
                        f"<div class='mono' style='font-size:13px;font-weight:600;'>£{_lo:,.2f} – £{_hi:,.2f}</div>"
                        f"<div style='font-size:10px;color:#64748B;margin-top:2px;'>at {_pos:.0f}% of range</div>",
                        unsafe_allow_html=True,
                    )
            with kc3:
                _v = _pd.get("vol_30d")
                _v_str = f"{_v:.1f}%" if _v is not None else "—"
                st.markdown(
                    f"<div style='font-size:10px;color:#64748B;text-transform:uppercase;letter-spacing:0.1em;'>30d vol (ann.)</div>"
                    f"<div class='mono' style='font-size:20px;font-weight:600;'>{_v_str}</div>",
                    unsafe_allow_html=True,
                )
            with kc4:
                _b = _pd.get("beta")
                _dy = _pd.get("dividend_yield")
                _beta_s = f"{_b:.2f}" if _b is not None else "—"
                _yld_s = f"{_dy:.2f}%" if _dy is not None else "—"
                st.markdown(
                    f"<div style='font-size:10px;color:#64748B;text-transform:uppercase;letter-spacing:0.1em;'>Beta · Yield</div>"
                    f"<div class='mono' style='font-size:16px;font-weight:600;'>{_beta_s} · {_yld_s}</div>",
                    unsafe_allow_html=True,
                )

            st.markdown("<div style='height:20px;'></div>", unsafe_allow_html=True)

            # ----- Price + volume (windowed by selected time frame)
            _h120 = _hist  # already time-frame windowed above
            _has_ohlc_cols = {"open", "high", "low"}.issubset(set(_h120.columns))
            _has_vol_col = "volume" in _h120.columns

            from plotly.subplots import make_subplots
            if _has_vol_col:
                fig_c = make_subplots(rows=2, cols=1, shared_xaxes=True,
                                      vertical_spacing=0.04, row_heights=[0.72, 0.28])
            else:
                fig_c = go.Figure()

            if _has_ohlc_cols:
                st.caption(f"Price · {_tf_deep} (candlestick + volume)")
                fig_c.add_trace(go.Candlestick(
                    x=_h120["date"],
                    open=_h120["open"], high=_h120["high"],
                    low=_h120["low"],   close=_h120["price"],
                    increasing_line_color="#00C896",
                    decreasing_line_color="#EF4444",
                    name=_pick, showlegend=False,
                ), row=1, col=1)
            else:
                st.caption(f"Price · {_tf_deep}")
                _price_kwargs = {"row": 1, "col": 1} if _has_vol_col else {}
                fig_c.add_trace(go.Scatter(
                    x=_h120["date"], y=_h120["price"], mode="lines",
                    line=dict(color="#0F172A", width=1.8),
                    name=_pick, showlegend=False,
                ), **_price_kwargs)

            # Overlay user's average purchase price as a horizontal line
            _avg_p = _info.get("avg_price")
            if _avg_p:
                _line_kwargs = dict(line_dash="dash", line_color="#3B82F6", line_width=1.5,
                                    annotation_text=f"Avg £{_avg_p:,.2f}",
                                    annotation_position="top left",
                                    annotation_font=dict(size=10, color="#3B82F6"))
                if _has_vol_col:
                    fig_c.add_hline(y=_avg_p, row=1, col=1, **_line_kwargs)
                else:
                    fig_c.add_hline(y=_avg_p, **_line_kwargs)

            if _has_vol_col:
                fig_c.add_trace(go.Bar(
                    x=_h120["date"], y=_h120["volume"],
                    marker_color="#CBD5E1", name="Volume", showlegend=False,
                ), row=2, col=1)

            fig_c.update_layout(
                height=480 if _has_vol_col else 380,
                margin=dict(l=40, r=20, t=10, b=30),
                paper_bgcolor="#FFFFFF", plot_bgcolor="#FFFFFF",
                font=dict(family="Helvetica Neue", size=12, color="#0F172A"),
                xaxis_rangeslider_visible=False,
            )
            fig_c.update_xaxes(gridcolor="#E5E7EB", tickfont=dict(color="#64748B", size=11))
            fig_c.update_yaxes(gridcolor="#E5E7EB", tickfont=dict(color="#64748B", size=11))
            st.plotly_chart(fig_c, use_container_width=True, config={"displayModeBar": False})

            # ----- P&L over time for this position (when cost basis is set)
            _avg_for_pnl = _info.get("avg_price")
            _units_for_pnl = _info.get("units")
            if _avg_for_pnl and _units_for_pnl:
                st.markdown("<div style='height:8px;'></div>", unsafe_allow_html=True)
                st.caption(
                    f"Position P/L over time · {_units_for_pnl:.0f} units at "
                    f"avg £{_avg_for_pnl:,.2f} (historical reconstruction)"
                )
                _pnl_series = (_hist["price"].astype(float) - float(_avg_for_pnl)) * float(_units_for_pnl)
                _pnl_pos = _pnl_series.where(_pnl_series >= 0)
                _pnl_neg = _pnl_series.where(_pnl_series < 0)
                fig_pp = go.Figure()
                # Positive area
                fig_pp.add_trace(go.Scatter(
                    x=_hist["date"], y=_pnl_pos, mode="lines",
                    line=dict(color="#00C896", width=1.5),
                    fill="tozeroy", fillcolor="rgba(0,200,150,0.15)",
                    name="Profit", showlegend=False,
                    hovertemplate="%{x|%d %b %Y}<br>£%{y:,.0f}<extra></extra>",
                ))
                # Negative area
                fig_pp.add_trace(go.Scatter(
                    x=_hist["date"], y=_pnl_neg, mode="lines",
                    line=dict(color="#EF4444", width=1.5),
                    fill="tozeroy", fillcolor="rgba(239,68,68,0.15)",
                    name="Loss", showlegend=False,
                    hovertemplate="%{x|%d %b %Y}<br>£%{y:,.0f}<extra></extra>",
                ))
                fig_pp.add_hline(y=0, line_color="#94A3B8", line_width=1)
                fig_pp.update_layout(
                    height=240, margin=dict(l=50, r=20, t=10, b=30),
                    paper_bgcolor="#FFFFFF", plot_bgcolor="#FFFFFF",
                    font=dict(family="Helvetica Neue", size=11, color="#0F172A"),
                )
                fig_pp.update_xaxes(gridcolor="#E5E7EB", tickfont=dict(color="#64748B", size=10))
                fig_pp.update_yaxes(gridcolor="#E5E7EB", tickfont=dict(color="#64748B", size=10),
                                    tickprefix="£", zeroline=False)
                st.plotly_chart(fig_pp, use_container_width=True, config={"displayModeBar": False})

            st.markdown("<div style='height:8px;'></div>", unsafe_allow_html=True)

            # ----- Drawdown timeseries + rolling vol
            dd_col, vol_col = st.columns(2)
            _close = _hist["price"].astype(float)
            _peak = _close.cummax()
            _dd = (_close / _peak - 1.0) * 100.0
            with dd_col:
                st.caption(f"Drawdown from running peak · {_tf_deep}")
                fig_d = go.Figure()
                fig_d.add_trace(go.Scatter(
                    x=_hist["date"], y=_dd, mode="lines",
                    fill="tozeroy", line=dict(color="#EF4444", width=1.5),
                    fillcolor="rgba(239,68,68,0.12)", showlegend=False,
                ))
                fig_d.add_hline(y=0, line_dash="dash", line_color="#94A3B8", line_width=1)
                fig_d.update_layout(
                    height=260, margin=dict(l=40, r=10, t=10, b=30),
                    paper_bgcolor="#FFFFFF", plot_bgcolor="#FFFFFF",
                    font=dict(family="Helvetica Neue", size=11, color="#0F172A"),
                )
                fig_d.update_xaxes(gridcolor="#E5E7EB", tickfont=dict(color="#64748B", size=10))
                fig_d.update_yaxes(gridcolor="#E5E7EB", tickfont=dict(color="#64748B", size=10),
                                   ticksuffix="%", zeroline=False)
                st.plotly_chart(fig_d, use_container_width=True, config={"displayModeBar": False})

            with vol_col:
                st.caption(f"Rolling 30d volatility · {_tf_deep} (annualised)")
                _daily_ret = _close.pct_change()
                _rvol = _daily_ret.rolling(30).std() * (252 ** 0.5) * 100
                fig_v = go.Figure()
                fig_v.add_trace(go.Scatter(
                    x=_hist["date"], y=_rvol, mode="lines",
                    line=dict(color="#3B82F6", width=1.6), showlegend=False,
                ))
                fig_v.update_layout(
                    height=260, margin=dict(l=40, r=10, t=10, b=30),
                    paper_bgcolor="#FFFFFF", plot_bgcolor="#FFFFFF",
                    font=dict(family="Helvetica Neue", size=11, color="#0F172A"),
                )
                fig_v.update_xaxes(gridcolor="#E5E7EB", tickfont=dict(color="#64748B", size=10))
                fig_v.update_yaxes(gridcolor="#E5E7EB", tickfont=dict(color="#64748B", size=10),
                                   ticksuffix="%")
                st.plotly_chart(fig_v, use_container_width=True, config={"displayModeBar": False})

            st.markdown("<div style='height:8px;'></div>", unsafe_allow_html=True)

            # ----- Returns histogram + monthly heatmap
            hi_col, hm_col = st.columns(2)
            with hi_col:
                st.caption(f"Daily returns distribution · {_tf_deep}")
                _r = _daily_ret.dropna() * 100
                if len(_r):
                    fig_h = go.Figure()
                    fig_h.add_trace(go.Histogram(
                        x=_r, nbinsx=40, marker_color="#0F172A",
                        opacity=0.85,
                    ))
                    fig_h.add_vline(x=0, line_dash="dash", line_color="#94A3B8", line_width=1)
                    fig_h.update_layout(
                        height=280, margin=dict(l=40, r=10, t=10, b=30),
                        paper_bgcolor="#FFFFFF", plot_bgcolor="#FFFFFF",
                        font=dict(family="Helvetica Neue", size=11, color="#0F172A"),
                        bargap=0.02, showlegend=False,
                    )
                    fig_h.update_xaxes(gridcolor="#E5E7EB", tickfont=dict(color="#64748B", size=10),
                                       ticksuffix="%")
                    fig_h.update_yaxes(gridcolor="#E5E7EB", tickfont=dict(color="#64748B", size=10))
                    st.plotly_chart(fig_h, use_container_width=True, config={"displayModeBar": False})

            with hm_col:
                st.caption("Monthly returns · last 24 months (full history)")
                # Heatmap always uses full history regardless of selected window
                _mhist = _hist_full.set_index("date")["price"].astype(float)
                _monthly = _mhist.resample("ME").last().pct_change().dropna() * 100
                _monthly = _monthly.tail(24)
                if len(_monthly):
                    _mdf = pd.DataFrame({
                        "year":  _monthly.index.year,
                        "month": _monthly.index.month,
                        "ret":   _monthly.values,
                    })
                    _pivot = _mdf.pivot(index="year", columns="month", values="ret")
                    _pivot.columns = [pd.Timestamp(2000, m, 1).strftime("%b") for m in _pivot.columns]
                    fig_m = px.imshow(
                        _pivot, color_continuous_scale="RdYlGn",
                        zmin=-max(abs(_monthly.min()), abs(_monthly.max())),
                        zmax= max(abs(_monthly.min()), abs(_monthly.max())),
                        text_auto=".1f", aspect="auto",
                    )
                    fig_m.update_layout(
                        height=280, margin=dict(l=40, r=10, t=10, b=10),
                        paper_bgcolor="#FFFFFF", plot_bgcolor="#FFFFFF",
                        font=dict(family="Helvetica Neue", size=10, color="#0F172A"),
                        coloraxis_showscale=False,
                    )
                    fig_m.update_xaxes(tickfont=dict(color="#64748B", size=10))
                    fig_m.update_yaxes(tickfont=dict(color="#64748B", size=10))
                    st.plotly_chart(fig_m, use_container_width=True, config={"displayModeBar": False})

            # ----- Holdings & P&L panel
            _pnl = position_pnl(_pick)
            if _pnl:
                _value, _cost, _pnl_abs, _pnl_pct = _pnl
                _c = pct_color(_pnl_pct)
                _avg = _info.get("avg_price")
                _units = _info.get("units")
                _curr = _pd["current"]
                _diff_per_share = _curr - _avg
                st.markdown("<div style='height:12px;'></div>", unsafe_allow_html=True)
                with st.container(border=True):
                    st.caption("Your position")
                    pc1, pc2, pc3, pc4 = st.columns(4)
                    pc1.markdown(
                        f"<div style='font-size:10px;color:#64748B;text-transform:uppercase;letter-spacing:0.1em;'>Cost basis</div>"
                        f"<div class='mono' style='font-size:16px;font-weight:600;'>£{_cost:,.2f}</div>"
                        f"<div style='font-size:10px;color:#64748B;'>{_units:.0f} × £{_avg:,.2f}</div>",
                        unsafe_allow_html=True,
                    )
                    pc2.markdown(
                        f"<div style='font-size:10px;color:#64748B;text-transform:uppercase;letter-spacing:0.1em;'>Current value</div>"
                        f"<div class='mono' style='font-size:16px;font-weight:600;'>£{_value:,.2f}</div>"
                        f"<div style='font-size:10px;color:#64748B;'>{_units:.0f} × £{_curr:,.2f}</div>",
                        unsafe_allow_html=True,
                    )
                    pc3.markdown(
                        f"<div style='font-size:10px;color:#64748B;text-transform:uppercase;letter-spacing:0.1em;'>Unrealised P/L</div>"
                        f"<div class='mono' style='font-size:16px;font-weight:600;color:{_c};'>{fmt_money(_pnl_abs, 2)}</div>"
                        f"<div class='mono' style='font-size:11px;font-weight:600;color:{_c};'>{fmt_signed_pct(_pnl_pct, 2)}</div>",
                        unsafe_allow_html=True,
                    )
                    pc4.markdown(
                        f"<div style='font-size:10px;color:#64748B;text-transform:uppercase;letter-spacing:0.1em;'>Per share</div>"
                        f"<div class='mono' style='font-size:16px;font-weight:600;color:{_c};'>{fmt_money(_diff_per_share, 2)}</div>"
                        f"<div style='font-size:10px;color:#64748B;'>vs £{_avg:,.2f} entry</div>",
                        unsafe_allow_html=True,
                    )
            else:
                st.caption("No holdings entered — open Manage ETFs in the sidebar to add an average purchase price + units.")

# ----------------------------------------------------------------------------- Insights (manual)
with tab_ai:
    # ---- News section
    st.markdown(
        "<div style='font-size:13px;font-weight:600;letter-spacing:0.04em;"
        "text-transform:uppercase;color:#64748B;margin-bottom:8px;'>📰 News</div>",
        unsafe_allow_html=True,
    )
    if not st.session_state.news_data:
        st.info(
            "Click **📰 Refresh news** in the sidebar to fetch latest headlines. "
            "Costs ~$0.07 per refresh."
        )
    else:
        high_items = []
        for t, data in st.session_state.news_data.items():
            for n in data.get("news", []):
                if isinstance(n, dict) and n.get("impact", "").lower() == "high":
                    high_items.append((t, n))

        if high_items:
            st.caption(f"High-impact news · {len(high_items)} items")
            for i in range(0, len(high_items), 2):
                row = high_items[i:i + 2]
                cols = st.columns(2)
                for col, (t, n) in zip(cols, row):
                    with col:
                        with st.container(border=True):
                            url = n.get("url", "")
                            source = n.get("source", "")
                            source_html = f'<a href="{url}" target="_blank" style="color:#64748B;font-size:10px;text-decoration:none;">{source} ↗</a>' if url else f'<span style="color:#64748B;font-size:10px;">{source}</span>'
                            st.markdown(
                                f"<div style='margin-bottom:6px;display:flex;align-items:center;gap:6px;'>"
                                f"<span style='background:#FEF2F2;color:#EF4444;font-size:9px;font-weight:700;padding:2px 5px;border-radius:3px;letter-spacing:0.08em;'>HIGH</span>"
                                f"<span class='mono' style='font-size:11px;font-weight:600;'>{t}</span>"
                                f"{source_html}"
                                f"</div>"
                                f"<div style='font-size:13px;line-height:1.4;color:#0F172A;'>{n.get('text', '')}</div>",
                                unsafe_allow_html=True,
                            )

        st.markdown("<div style='height:16px;'></div>", unsafe_allow_html=True)
        st.caption("All news, by ETF")
        for ticker in st.session_state.etfs:
            items = st.session_state.news_data.get(ticker, {}).get("news", [])
            if not items:
                continue
            label = f"{ticker} · {st.session_state.etfs[ticker]['name']} ({len(items)})"
            with st.expander(label, expanded=False):
                for n in items:
                    if isinstance(n, dict):
                        impact = n.get("impact", "low").upper()
                        text = n.get("text", "")
                        source = n.get("source", "")
                        url = n.get("url", "")
                        impact_color = {"HIGH": "#EF4444", "MEDIUM": "#F59E0B", "LOW": "#94A3B8"}.get(impact, "#94A3B8")
                        impact_bg = {"HIGH": "#FEF2F2", "MEDIUM": "#FEF3C7", "LOW": "#F1F3F6"}.get(impact, "#F1F3F6")
                        source_html = f'<a href="{url}" target="_blank" style="color:#64748B;font-size:10px;text-decoration:none;">{source} ↗</a>' if url else f'<span style="color:#64748B;font-size:10px;">{source}</span>'
                        st.markdown(
                            f"<div style='padding:10px 0;border-bottom:1px solid #E5E7EB;'>"
                            f"<div style='display:flex;align-items:center;gap:6px;margin-bottom:4px;'>"
                            f"<span style='background:{impact_bg};color:{impact_color};font-size:9px;font-weight:700;padding:2px 5px;border-radius:3px;letter-spacing:0.08em;'>{impact}</span>"
                            f"{source_html}"
                            f"</div>"
                            f"<div style='font-size:13px;line-height:1.4;color:#0F172A;'>{text}</div>"
                            f"</div>",
                            unsafe_allow_html=True,
                        )

    st.markdown("<div style='height:32px;'></div>", unsafe_allow_html=True)

    # ---- Analysis section
    st.markdown(
        "<div style='font-size:13px;font-weight:600;letter-spacing:0.04em;"
        "text-transform:uppercase;color:#64748B;margin-bottom:8px;'>✨ Portfolio analysis</div>",
        unsafe_allow_html=True,
    )
    if st.session_state.analysis:
        with st.container(border=True):
            st.markdown(st.session_state.analysis)
    else:
        st.info(
            "Click **✨ Analyse portfolio** in the sidebar to generate "
            "AI-powered insights. Costs ~$0.02 per run."
        )
