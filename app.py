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
import pandas as pd
import anthropic
import json
from datetime import datetime, timedelta

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
        color: #0F172A;
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
    [data-testid="stSidebar"] .stButton button[kind="primary"] {
        background: #0F172A;
        color: #FFFFFF;
        border-color: #0F172A;
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

if "etfs"            not in st.session_state: st.session_state.etfs = DEFAULT_ETFS.copy()
if "allocs"          not in st.session_state: st.session_state.allocs = DEFAULT_ALLOCS.copy()
if "news_data"       not in st.session_state: st.session_state.news_data = {}
if "analysis"        not in st.session_state: st.session_state.analysis = ""
if "price_data"      not in st.session_state: st.session_state.price_data = {}
if "last_news_fetch" not in st.session_state: st.session_state.last_news_fetch = None
if "api_spend"       not in st.session_state: st.session_state.api_spend = 0.0

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
    """Fetch price history from Yahoo Finance. Preserved from original."""
    results = {}
    end = datetime.today()
    start = end - timedelta(days=95)
    for ticker, yahoo in etf_pairs:
        try:
            raw = yf.download(yahoo, start=start, end=end, progress=False, auto_adjust=True)
            if raw.empty: results[ticker] = None; continue
            if isinstance(raw.columns, pd.MultiIndex): raw.columns = raw.columns.get_level_values(0)
            close = raw["Close"].dropna()
            if len(close) < 2: results[ticker] = None; continue
            now = float(close.iloc[-1])
            w1  = float(close.iloc[-6])  if len(close) >= 6  else now
            m1  = float(close.iloc[-22]) if len(close) >= 22 else now
            m3  = float(close.iloc[-66]) if len(close) >= 66 else now
            results[ticker] = {
                "current": now,
                "ret_1w": (now-w1)/w1*100,
                "ret_1m": (now-m1)/m1*100,
                "ret_3m": (now-m3)/m3*100,
                "history": pd.DataFrame({"date":close.index,"price":close.values}),
            }
        except Exception: results[ticker] = None
    return results

def fetch_news_and_ratings(etfs):
    """Fetch news and ratings from Claude API. Preserved from original."""
    client = anthropic.Anthropic(api_key=api_key)
    tickers_str = ", ".join(f"{t} ({v['name']})" for t,v in etfs.items())
    prompt = f"""Search for the most recent news (last 2 weeks) for these LSE-listed ETFs: {tickers_str}.

Return ONLY a raw JSON object. No markdown. Structure:
{{
  "TICKER": {{
    "sentiment": "bullish" | "neutral" | "bearish",
    "rating": "buy" | "hold" | "sell",
    "analyst_view": "analyst consensus or price target if available, else empty string",
    "news": [
      {{"text": "headline or development", "impact": "high" | "medium" | "low"}},
      {{"text": "second item", "impact": "medium"}}
    ],
    "drivers": "one sentence key driver"
  }}
}}
Include all tickers. Raw JSON only."""
    try:
        msg = client.messages.create(
            model="claude-opus-4-7",
            max_tokens=4000,
            messages=[{"role":"user","content":prompt}],
        )
        text = msg.content[0].text
        clean = text.replace("```json","").replace("```","").strip()
        json_str = clean[clean.index("{"):clean.rindex("}")+1]
        return json.loads(json_str)
    except Exception as e:
        st.error(f"API error: {e}")
        return {t: {"sentiment": "neutral", "rating": "hold", "news": [], "drivers": ""} for t in etfs}

def generate_analysis(allocs, news, price_data, etfs):
    """Generate Claude portfolio analysis. Preserved from original."""
    client = anthropic.Anthropic(api_key=api_key)
    alloc_str  = ", ".join(f"{t} {v}%" for t,v in allocs.items())
    price_str  = "".join(f"{t}: 1W={d['ret_1w']:+.1f}% 1M={d['ret_1m']:+.1f}% 3M={d['ret_3m']:+.1f}%\n" for t,d in price_data.items() if d)
    sell_list  = [t for t,v in news.items() if v.get("rating")=="sell"]
    buy_list   = [t for t,v in news.items() if v.get("rating")=="buy"]
    high_news  = [(t,i["text"]) for t,v in news.items() for i in v.get("news",[]) if isinstance(i,dict) and i.get("impact")=="high"]
    msg = client.messages.create(
        model="claude-opus-4-7",
        max_tokens=1500,
        messages=[{"role":"user","content":
            f"Portfolio analyst. Allocation: {alloc_str}\nPrice: {price_str}\n"
            f"Buy signals: {buy_list}\nSell signals: {sell_list}\nHigh-impact news: {high_news}\n"
            f"Full data: {json.dumps(news)}\n\n"
            "Write 3 paragraphs: (1) overall health vs momentum and ratings, "
            "(2) immediate attention items, (3) top 3 watch items with one-line action each. "
            "Be specific, reference tickers and numbers. No bullets. No preamble."}],
    )
    return msg.content[0].text

# =============================================================================
# Helpers
# =============================================================================

def rating_html(rating):
    """Return HTML for rating pill."""
    cls = {"buy":"rating-buy", "hold":"rating-hold", "sell":"rating-sell"}.get(rating.lower(), "rating-hold")
    return f'<span class="rating-pill {cls}">{(rating or "—").upper()}</span>'

def pct_color(v):
    """Return color for percentage value."""
    if v > 0.05:  return "#00C896"
    if v < -0.05: return "#EF4444"
    return "#64748B"

def fmt_signed_pct(v, digits=2):
    """Format percentage with sign."""
    s = f"{v:.{digits}f}"
    return ("+" + s if v > 0 else s) + "%"

# =============================================================================
# Sidebar
# =============================================================================

with st.sidebar:
    st.markdown("## Portfolio")
    st.caption(f"{len(st.session_state.etfs)} ETFs · GBP")

    # ---- allocations
    st.caption("Allocations")
    total = sum(st.session_state.allocs.values())
    col_a, col_b = st.columns([1, 1])
    with col_a:
        st.markdown(f"<span class='mono' style='font-size:13px;'>Total</span>", unsafe_allow_html=True)
    with col_b:
        color = "#0F172A" if abs(total - 100) < 0.01 else "#F59E0B"
        st.markdown(
            f"<div class='mono' style='text-align:right;font-weight:600;color:{color};'>{total:.1f}% <span style='color:#94A3B8;font-weight:400;'>/ 100%</span></div>",
            unsafe_allow_html=True,
        )
    st.progress(min(total, 100) / 100.0)

    # editable sliders + numeric input
    for ticker, info in st.session_state.etfs.items():
        col_slider, col_input = st.columns([3, 1])
        with col_slider:
            new_val = st.slider(
                ticker,
                min_value=0.0, max_value=60.0, step=0.5,
                value=float(st.session_state.allocs.get(ticker, 0.0)),
                key=f"slider_{ticker}",
                label_visibility="visible",
            )
        with col_input:
            num_val = st.number_input(
                f"alloc_{ticker}",
                min_value=0.0, max_value=60.0, step=0.5,
                value=float(st.session_state.allocs.get(ticker, 0.0)),
                key=f"num_{ticker}",
                label_visibility="collapsed",
            )
            new_val = num_val if num_val != float(st.session_state.allocs.get(ticker, 0.0)) else new_val
        st.session_state.allocs[ticker] = new_val

    st.divider()

    # ---- universe (add / remove)
    st.caption("Universe")
    with st.expander("Add / Remove ETF", expanded=False):
        c1, c2 = st.columns([2, 1])
        with c1:
            new_ticker = st.text_input("Ticker", placeholder="e.g. IWDA", label_visibility="collapsed")
        with c2:
            if st.button("Add", use_container_width=True):
                t = (new_ticker or "").strip().upper()
                if t and t not in st.session_state.etfs:
                    st.session_state.etfs[t] = {"name": t, "yahoo": f"{t}.L", "cat": "Satellite"}
                    st.session_state.allocs[t] = 0.0
                    st.rerun()

        st.caption("Remove")
        for ticker in list(st.session_state.etfs.keys()):
            rc1, rc2 = st.columns([3, 1])
            rc1.markdown(f"<span class='mono' style='font-size:12px;'>{ticker}</span>", unsafe_allow_html=True)
            if rc2.button("✕", key=f"rm_{ticker}", help=f"Remove {ticker}"):
                del st.session_state.etfs[ticker]
                st.session_state.allocs.pop(ticker, None)
                st.rerun()

    st.divider()

    # ---- api credits
    st.caption("API credits")
    hrs = hours_since_last_fetch()
    next_refresh = max(0, API_MIN_REFRESH_HRS - (int(hrs) if hrs else 0))
    st.caption(
        f"${st.session_state.api_spend:.3f} used · refresh in {next_refresh}h"
    )

    st.divider()

    # ---- action buttons
    st.markdown("<div style='margin-bottom:12px;'></div>", unsafe_allow_html=True)

    force = st.toggle("Force refresh (override throttle)", value=False, key="force_refresh")

    st.markdown("<div style='margin-bottom:8px;'></div>", unsafe_allow_html=True)

    if st.button("↻ Refresh prices", use_container_width=True):
        with st.spinner("Fetching prices…"):
            etf_pairs = tuple((t, v["yahoo"]) for t, v in st.session_state.etfs.items())
            st.session_state.price_data = fetch_price_data(etf_pairs)
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

    st.markdown("<div style='margin-bottom:12px;'></div>", unsafe_allow_html=True)

# =============================================================================
# Header
# =============================================================================

st.markdown("# ETF Tracker")
st.markdown(
    f"<div style='color:#64748B;font-size:13px;margin-bottom:24px;'>"
    f"Portfolio sentiment dashboard · {len(st.session_state.etfs)} positions"
    f"</div>",
    unsafe_allow_html=True,
)

# =============================================================================
# Top metrics row
# =============================================================================

m1, m2, m3, m4 = st.columns(4)
with m1:
    st.metric("Portfolio value", "£248,412", "+0.84%")
with m2:
    st.metric("Month to date", "+3.42%", "vs benchmark")
with m3:
    buy_n = sum(1 for v in st.session_state.news_data.values() if v.get("rating","").lower() == "buy")
    hold_n = sum(1 for v in st.session_state.news_data.values() if v.get("rating","").lower() == "hold")
    sell_n = sum(1 for v in st.session_state.news_data.values() if v.get("rating","").lower() == "sell")
    st.metric("Signals", f"{buy_n}B · {hold_n}H · {sell_n}S", "from Claude")
with m4:
    st.metric("Portfolio status", "On track", "balanced")

# =============================================================================
# Tabs
# =============================================================================

tab_pos, tab_perf, tab_news, tab_analysis = st.tabs(
    ["Positions", "Performance", "News & signals", "Analysis"]
)

# ----------------------------------------------------------------------------- Positions
with tab_pos:
    core_etfs = {t: v for t, v in st.session_state.etfs.items() if v["cat"] == "Core"}
    sat_etfs = {t: v for t, v in st.session_state.etfs.items() if v["cat"] == "Satellite"}

    def render_etf_card(ticker):
        info = st.session_state.etfs[ticker]
        rating_data = st.session_state.news_data.get(ticker, {})
        rating = rating_data.get("rating", "hold")
        price_data = st.session_state.price_data.get(ticker)
        n_items = rating_data.get("news", [])

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
                        f"<div class='mono' style='font-size:18px;font-weight:600;text-align:right;'>£{last_price:.2f}</div>"
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

            label = f"News ({len(n_items)})"
            with st.expander(label, expanded=False):
                if not n_items:
                    st.caption("No recent news.")
                else:
                    for n in n_items[:5]:
                        if isinstance(n, dict):
                            impact = n.get("impact", "low").upper()
                            text = n.get("text", "")
                            impact_color = {"HIGH": "#EF4444", "MEDIUM": "#F59E0B", "LOW": "#94A3B8"}.get(impact, "#94A3B8")
                            impact_bg = {"HIGH": "#FEF2F2", "MEDIUM": "#FEF3C7", "LOW": "#F1F3F6"}.get(impact, "#F1F3F6")
                            st.markdown(
                                f"<div style='padding:8px 0;border-bottom:1px solid #E5E7EB;'>"
                                f"<div style='display:flex;align-items:center;gap:6px;margin-bottom:4px;'>"
                                f"<span style='background:{impact_bg};color:{impact_color};font-size:9px;font-weight:700;padding:2px 5px;border-radius:3px;letter-spacing:0.08em;'>{impact}</span>"
                                f"</div>"
                                f"<div style='font-size:12px;line-height:1.4;color:#0F172A;'>{text}</div>"
                                f"</div>",
                                unsafe_allow_html=True,
                            )

    # --- core section
    core_pct = sum(st.session_state.allocs.get(t, 0) for t in core_etfs)
    sat_pct = sum(st.session_state.allocs.get(t, 0) for t in sat_etfs)

    head_c1, head_c2 = st.columns([4, 1])
    head_c1.caption(f"Core · {core_pct:.0f}%")
    head_c2.markdown("<div style='text-align:right;color:#64748B;font-size:12px;padding-top:2px;'>broad-market beta</div>", unsafe_allow_html=True)

    core_list = list(core_etfs.keys())
    for row_start in range(0, len(core_list), 4):
        cols = st.columns(4)
        for col, ticker in zip(cols, core_list[row_start:row_start + 4]):
            with col:
                render_etf_card(ticker)

    st.markdown("<div style='height:16px;'></div>", unsafe_allow_html=True)

    head_s1, head_s2 = st.columns([4, 1])
    head_s1.caption(f"Satellite · {sat_pct:.0f}%")
    head_s2.markdown("<div style='text-align:right;color:#64748B;font-size:12px;padding-top:2px;'>thematic overlay</div>", unsafe_allow_html=True)

    sat_list = list(sat_etfs.keys())
    for row_start in range(0, len(sat_list), 4):
        cols = st.columns(4)
        for col, ticker in zip(cols, sat_list[row_start:row_start + 4]):
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

# ----------------------------------------------------------------------------- News & signals
with tab_news:
    high_items = []
    for t, data in st.session_state.news_data.items():
        for n in data.get("news", []):
            if isinstance(n, dict) and n.get("impact", "").lower() == "high":
                high_items.append((t, n))

    st.caption(f"High-impact news · {len(high_items)} items")

    if high_items:
        for i in range(0, len(high_items), 2):
            row = high_items[i:i + 2]
            cols = st.columns(2)
            for col, (t, n) in zip(cols, row):
                with col:
                    with st.container(border=True):
                        st.markdown(
                            f"<div style='margin-bottom:6px;'>"
                            f"<span style='background:#FEF2F2;color:#EF4444;font-size:9px;font-weight:700;padding:2px 5px;border-radius:3px;letter-spacing:0.08em;'>HIGH</span>"
                            f"<span class='mono' style='font-size:11px;font-weight:600;margin-left:6px;'>{t}</span>"
                            f"</div>"
                            f"<div style='font-size:13px;line-height:1.4;color:#0F172A;'>{n.get('text', '')}</div>",
                            unsafe_allow_html=True,
                        )

    st.markdown("<div style='height:24px;'></div>", unsafe_allow_html=True)

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
                    impact_color = {"HIGH": "#EF4444", "MEDIUM": "#F59E0B", "LOW": "#94A3B8"}.get(impact, "#94A3B8")
                    impact_bg = {"HIGH": "#FEF2F2", "MEDIUM": "#FEF3C7", "LOW": "#F1F3F6"}.get(impact, "#F1F3F6")
                    st.markdown(
                        f"<div style='padding:10px 0;border-bottom:1px solid #E5E7EB;'>"
                        f"<div style='display:flex;align-items:center;gap:6px;margin-bottom:4px;'>"
                        f"<span style='background:{impact_bg};color:{impact_color};font-size:9px;font-weight:700;padding:2px 5px;border-radius:3px;letter-spacing:0.08em;'>{impact}</span>"
                        f"</div>"
                        f"<div style='font-size:13px;line-height:1.4;color:#0F172A;'>{text}</div>"
                        f"</div>",
                        unsafe_allow_html=True,
                    )

# ----------------------------------------------------------------------------- Analysis
with tab_analysis:
    st.caption("Portfolio analysis")
    if st.session_state.analysis:
        with st.container(border=True):
            st.markdown(st.session_state.analysis)
    else:
        st.info("Click **Analyse portfolio** in the sidebar to generate AI-powered insights.")
