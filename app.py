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
    hc1, hc2 = st.columns(2)
    with hc1:
        new_avg = st.number_input(
            "Avg price (£)", min_value=0.0, step=0.01,
            value=float(info.get("avg_price") or 0.0),
            key=f"avg_{ticker}",
            help="Average price per share you paid, in £.",
        )
    with hc2:
        new_units = st.number_input(
            "Units", min_value=0.0, step=1.0,
            value=float(info.get("units") or 0.0),
            key=f"units_{ticker}",
            help="Number of shares held.",
        )
    if st.button("Save holdings", key=f"hold_save_{ticker}", use_container_width=True):
        # Treat zeros as "cleared" — drop fields so P&L row hides
        if new_avg > 0 and new_units > 0:
            st.session_state.etfs[ticker]["avg_price"] = new_avg
            st.session_state.etfs[ticker]["units"] = new_units
        else:
            st.session_state.etfs[ticker].pop("avg_price", None)
            st.session_state.etfs[ticker].pop("units", None)
        save_holdings(st.session_state.etfs)
        st.rerun()

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

# =============================================================================
# Header stat strip — live weighted returns + position count
# =============================================================================

weighted_1m = sum(
    (st.session_state.allocs.get(t, 0) / 100.0) * (pd_.get("ret_1m") or 0)
    for t, pd_ in st.session_state.price_data.items() if pd_
)
weighted_3m = sum(
    (st.session_state.allocs.get(t, 0) / 100.0) * (pd_.get("ret_3m") or 0)
    for t, pd_ in st.session_state.price_data.items() if pd_
)
n_positions = len(st.session_state.etfs)
_port_pnl = portfolio_pnl()
_pnl_segment = ""
if _port_pnl:
    _value, _cost, _pnl_abs, _pnl_pct = _port_pnl
    _c = pct_color(_pnl_pct)
    _pnl_segment = (
        f" · <span class='mono' style='font-weight:600;color:#0F172A;'>Value £{_value:,.0f}</span>"
        f" · <span class='mono' style='font-weight:600;color:{_c};'>"
        f"P/L {fmt_money(_pnl_abs)} ({fmt_signed_pct(_pnl_pct, 1)})</span>"
    )
st.markdown(
    f"<div style='color:#64748B;font-size:13px;margin-bottom:24px;'>"
    f"{n_positions} positions"
    f"{_pnl_segment}"
    f" · <span class='mono' style='color:{pct_color(weighted_1m)};font-weight:600;'>"
    f"1M {fmt_signed_pct(weighted_1m, 1)}</span>"
    f" · <span class='mono' style='color:{pct_color(weighted_3m)};font-weight:600;'>"
    f"3M {fmt_signed_pct(weighted_3m, 1)}</span>"
    f"</div>",
    unsafe_allow_html=True,
)

# =============================================================================
# Tabs
# =============================================================================

tab_over, tab_perf, tab_deep, tab_ai = st.tabs(
    ["Overview", "Performance", "Deep dive", "Insights"]
)

# ----------------------------------------------------------------------------- Overview
with tab_over:
    # "What changed since last refresh" strip
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
    st.caption("Normalised price · 90 days, rebased to 100")

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
            df = price_info["history"]
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
    st.caption("Risk vs return · 3-month return × 30-day volatility")
    scatter_rows = []
    for t, info in st.session_state.etfs.items():
        pd_ = st.session_state.price_data.get(t)
        if not pd_: continue
        scatter_rows.append({
            "ticker": t,
            "ret_3m": pd_.get("ret_3m") or 0.0,
            "vol_30d": pd_.get("vol_30d") or 0.0,
            "allocation": st.session_state.allocs.get(t, 0.0),
            "rating": (st.session_state.news_data.get(t) or {}).get("rating", "hold").upper(),
        })
    if scatter_rows:
        sdf = pd.DataFrame(scatter_rows)
        rating_colors = {"BUY": "#00C896", "HOLD": "#F59E0B", "SELL": "#EF4444"}
        fig2 = px.scatter(
            sdf, x="ret_3m", y="vol_30d", size="allocation", color="rating",
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
            xaxis_title="3-month return (%)", yaxis_title="30-day volatility (%)",
        )
        fig2.update_xaxes(gridcolor="#E5E7EB", tickfont=dict(color="#64748B", size=11))
        fig2.update_yaxes(gridcolor="#E5E7EB", tickfont=dict(color="#64748B", size=11))
        st.plotly_chart(fig2, use_container_width=True, config={"displayModeBar": False})

    st.markdown("<div style='height:24px;'></div>", unsafe_allow_html=True)

    # ---------- Correlation heatmap (90-day daily returns)
    st.caption("Correlation · 90-day daily returns")
    ret_frames = {}
    for t in st.session_state.etfs:
        pd_ = st.session_state.price_data.get(t)
        if pd_ and not pd_.get("history", pd.DataFrame()).empty:
            h = pd_["history"].copy()
            h = h.set_index("date")["price"].astype(float)
            ret_frames[t] = h.pct_change().dropna().tail(90)
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
    st.caption("Drawdown from running peak · %")
    fig4 = go.Figure()
    plotted = 0
    for i, t in enumerate(picks):
        pd_ = st.session_state.price_data.get(t)
        if not pd_ or pd_.get("history", pd.DataFrame()).empty: continue
        h = pd_["history"].copy().sort_values("date")
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

# ----------------------------------------------------------------------------- Deep dive
with tab_deep:
    _tickers = list(st.session_state.etfs.keys())
    if not _tickers:
        st.info("Add an ETF in the sidebar to see its deep-dive view.")
    else:
        _pick = st.selectbox(
            "ETF",
            options=_tickers,
            format_func=lambda t: f"{t} — {st.session_state.etfs[t]['name']}",
            key="deep_pick",
        )
        _info = st.session_state.etfs[_pick]
        _pd = st.session_state.price_data.get(_pick)

        if not _pd or _pd.get("history", pd.DataFrame()).empty:
            st.warning(
                f"No price data for {_pick}. Click ↻ Refresh prices in the sidebar."
            )
        else:
            _hist = _pd["history"].copy()
            _hist["date"] = pd.to_datetime(_hist["date"])
            _hist = _hist.sort_values("date").reset_index(drop=True)

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

            # ----- Candlestick + volume (last 120 sessions)
            st.caption("Price · last 120 sessions (candlestick + volume)")
            _h120 = _hist.tail(120)
            from plotly.subplots import make_subplots
            fig_c = make_subplots(rows=2, cols=1, shared_xaxes=True,
                                  vertical_spacing=0.04, row_heights=[0.72, 0.28])
            fig_c.add_trace(go.Candlestick(
                x=_h120["date"],
                open=_h120["open"], high=_h120["high"],
                low=_h120["low"],   close=_h120["price"],
                increasing_line_color="#00C896",
                decreasing_line_color="#EF4444",
                name=_pick, showlegend=False,
            ), row=1, col=1)
            fig_c.add_trace(go.Bar(
                x=_h120["date"], y=_h120["volume"],
                marker_color="#CBD5E1", name="Volume", showlegend=False,
            ), row=2, col=1)
            fig_c.update_layout(
                height=480, margin=dict(l=40, r=20, t=10, b=30),
                paper_bgcolor="#FFFFFF", plot_bgcolor="#FFFFFF",
                font=dict(family="Helvetica Neue", size=12, color="#0F172A"),
                xaxis_rangeslider_visible=False,
            )
            fig_c.update_xaxes(gridcolor="#E5E7EB", tickfont=dict(color="#64748B", size=11))
            fig_c.update_yaxes(gridcolor="#E5E7EB", tickfont=dict(color="#64748B", size=11))
            st.plotly_chart(fig_c, use_container_width=True, config={"displayModeBar": False})

            st.markdown("<div style='height:8px;'></div>", unsafe_allow_html=True)

            # ----- Drawdown timeseries + rolling vol
            dd_col, vol_col = st.columns(2)
            _close = _hist["price"].astype(float)
            _peak = _close.cummax()
            _dd = (_close / _peak - 1.0) * 100.0
            with dd_col:
                st.caption("Drawdown from running peak")
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
                st.caption("Rolling 30d volatility (annualised)")
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
                st.caption("Daily returns distribution")
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
                st.caption("Monthly returns · last 24 months")
                _mhist = _hist.set_index("date")["price"].astype(float)
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
