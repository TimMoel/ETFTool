import streamlit as st
import yfinance as yf
import plotly.graph_objects as go
import plotly.express as px
import pandas as pd
import anthropic
import json
from datetime import datetime, timedelta

# ─── API key from Streamlit secrets (set in deployment dashboard)
api_key = st.secrets["ANTHROPIC_API_KEY"]

# ─── Page config ────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="ETF Sentiment Dashboard",
    page_icon="📊",
    layout="wide",
)

st.markdown("""
<style>
    .metric-card {
        background: #f8f9fa;
        border: 1px solid #e0e0e0;
        border-radius: 8px;
        padding: 14px 16px;
        margin-bottom: 8px;
    }
    .bullish { color: #0f6e56; font-weight: 600; }
    .neutral { color: #854f0b; font-weight: 600; }
    .bearish { color: #a32d2d; font-weight: 600; }
    .badge-bullish {
        background: #e1f5ee; color: #0f6e56;
        padding: 2px 8px; border-radius: 4px;
        font-size: 12px; font-weight: 600;
    }
    .badge-neutral {
        background: #faeeda; color: #854f0b;
        padding: 2px 8px; border-radius: 4px;
        font-size: 12px; font-weight: 600;
    }
    .badge-bearish {
        background: #fcebeb; color: #a32d2d;
        padding: 2px 8px; border-radius: 4px;
        font-size: 12px; font-weight: 600;
    }
    div[data-testid="metric-container"] {
        background: #f8f9fa;
        border: 1px solid #e0e0e0;
        border-radius: 8px;
        padding: 12px 16px;
    }
</style>
""", unsafe_allow_html=True)

# ─── ETF universe ─────────────────────────────────────────────────────────
ETFs = {
    "VWRP": {"name": "Global all-world",   "yahoo": "VWRP.L", "cat": "Core"},
    "XMWX": {"name": "Developed ex-US",    "yahoo": "XMWX.L", "cat": "Core"},
    "EMIM": {"name": "Emerging markets",   "yahoo": "EMIM.L", "cat": "Core"},
    "CSH2": {"name": "Cash/overnight",     "yahoo": "CSH2.L", "cat": "Core"},
    "SPDR": {"name": "S&P 500 UCITS",      "yahoo": "SPDR.L", "cat": "Core"},
    "VEUR": {"name": "Europe",             "yahoo": "VEUR.L", "cat": "Core"},
    "NATP": {"name": "Defence global",     "yahoo": "NATP.L", "cat": "Satellite"},
    "NUCG": {"name": "Nuclear/uranium",    "yahoo": "NUCG.L", "cat": "Satellite"},
    "WDEP": {"name": "Defence Europe",     "yahoo": "WDEP.L", "cat": "Satellite"},
    "BUGG": {"name": "Cybersecurity",      "yahoo": "BUGG.L", "cat": "Satellite"},
    "ARMG": {"name": "Defence tech",       "yahoo": "ARMG.L", "cat": "Satellite"},
    "RBTX": {"name": "Robotics",           "yahoo": "RBTX.L", "cat": "Satellite"},
}

DEFAULT_ALLOCS = {
    "VWRP": 47.0, "XMWX": 10.0, "EMIM": 10.0, "CSH2": 5.0,
    "SPDR": 6.0,  "VEUR": 4.0,
    "NATP": 3.0,  "NUCG": 3.0,  "WDEP": 3.0,
    "BUGG": 3.0,  "ARMG": 3.0,  "RBTX": 3.0,
}

# ─── Session state defaults ───────────────────────────────────────────────
if "allocs" not in st.session_state:
    st.session_state.allocs = DEFAULT_ALLOCS.copy()
if "news_data" not in st.session_state:
    st.session_state.news_data = {}
if "analysis" not in st.session_state:
    st.session_state.analysis = ""
if "price_data" not in st.session_state:
    st.session_state.price_data = {}

# ─── Data fetching ────────────────────────────────────────────────────────
@st.cache_data(ttl=900)  # 15-minute cache
def fetch_price_data(tickers_dict):
    results = {}
    end = datetime.today()
    start = end - timedelta(days=95)

    for ticker, info in tickers_dict.items():
        try:
            raw = yf.download(
                info["yahoo"], start=start, end=end,
                progress=False, auto_adjust=True
            )
            if raw.empty:
                results[ticker] = None
                continue

            # yfinance returns multi-level columns — flatten them
            if isinstance(raw.columns, pd.MultiIndex):
                raw.columns = raw.columns.get_level_values(0)

            close = raw["Close"].dropna()
            if len(close) < 2:
                results[ticker] = None
                continue

            now = float(close.iloc[-1])
            w1  = float(close.iloc[-6])  if len(close) >= 6  else now
            m1  = float(close.iloc[-22]) if len(close) >= 22 else now
            m3  = float(close.iloc[-66]) if len(close) >= 66 else now

            results[ticker] = {
                "current": now,
                "ret_1w":  (now - w1) / w1 * 100,
                "ret_1m":  (now - m1) / m1 * 100,
                "ret_3m":  (now - m3) / m3 * 100,
                "history": pd.DataFrame({"date": close.index, "price": close.values}),
            }
        except Exception:
            results[ticker] = None

    return results


def fetch_news_and_sentiment(api_key: str):
    client = anthropic.Anthropic(api_key=api_key)
    tickers_str = ", ".join(f"{t} ({v['name']})" for t, v in ETFs.items())

    with client.messages.stream(
        model="claude-opus-4-5-20251101",
        max_tokens=4000,
        tools=[{"type": "web_search_20250305", "name": "web_search"}],
        messages=[{
            "role": "user",
            "content": (
                f"Search for the most recent news and market developments (last 2 weeks) "
                f"for these ETFs listed on the London Stock Exchange: {tickers_str}.\n\n"
                "After searching, return ONLY a JSON object with no markdown or code fences. Structure:\n"
                '{\n'
                '  "TICKER": {\n'
                '    "sentiment": "bullish" or "neutral" or "bearish",\n'
                '    "news": ["headline or development 1", "headline or development 2"],\n'
                '    "drivers": "One sentence key driver"\n'
                '  }\n'
                '}\n\n'
                "Include all 12 tickers. Raw JSON only."
            ),
        }],
        betas=["web-search-2025-03-05"],
    ) as stream:
        text = stream.get_final_text()

    clean = text.replace("```json", "").replace("```", "").strip()
    start = clean.index("{")
    end   = clean.rindex("}") + 1
    return json.loads(clean[start:end])


def generate_analysis(api_key: str, allocs: dict, news: dict, price_data: dict):
    client = anthropic.Anthropic(api_key=api_key)

    alloc_str = ", ".join(f"{t} {v}%" for t, v in allocs.items())
    price_str = ""
    for t, d in price_data.items():
        if d:
            price_str += (
                f"{t}: 1W={d['ret_1w']:+.1f}%, 1M={d['ret_1m']:+.1f}%, "
                f"3M={d['ret_3m']:+.1f}%\n"
            )
    news_str = json.dumps(news, indent=2) if news else "No news loaded"

    msg = client.messages.create(
        model="claude-opus-4-5-20251101",
        max_tokens=1500,
        messages=[{
            "role": "user",
            "content": (
                f"You are a portfolio analyst. Given:\n\n"
                f"ALLOCATION: {alloc_str}\n\n"
                f"PRICE PERFORMANCE:\n{price_str}\n\n"
                f"NEWS SENTIMENT:\n{news_str}\n\n"
                "Write a concise 3-paragraph analysis:\n"
                "1. Does allocation weighting match current sentiment and price momentum?\n"
                "2. Concentration risks or mismatches between conviction weight and signals?\n"
                "3. Top 3 positions to watch this week and a brief action for each.\n\n"
                "Be direct and specific. Reference actual return figures. No bullet points."
            ),
        }],
    )
    return msg.content[0].text


# ─── Sidebar ─────────────────────────────────────────────────────────────
with st.sidebar:
    st.title("⚙️ Settings")
    st.divider()

    st.subheader("Allocations")
    total = 0.0
    new_allocs = {}
    for cat in ["Core", "Satellite"]:
        st.caption(cat)
        for ticker, info in ETFs.items():
            if info["cat"] == cat:
                val = st.number_input(
                    f"{ticker} — {info['name']}",
                    min_value=0.0, max_value=100.0, step=0.5,
                    value=float(st.session_state.allocs[ticker]),
                    key=f"alloc_{ticker}",
                )
                new_allocs[ticker] = val
                total += val

    st.session_state.allocs = new_allocs
    delta = total - 100.0
    if abs(delta) < 0.01:
        st.success(f"Total: {total:.1f}% ✓")
    else:
        st.error(f"Total: {total:.1f}% ({delta:+.1f}%)")

    st.divider()
    col1, col2 = st.columns(2)
    with col1:
        refresh_prices = st.button("↻ Prices", use_container_width=True)
    with col2:
        refresh_news   = st.button("↻ News",   use_container_width=True)
    run_analysis = st.button("Analyse portfolio", use_container_width=True,
                              type="primary")



# ─── Fetch price data ────────────────────────────────────────────────────
if refresh_prices or not st.session_state.price_data:
    with st.spinner("Fetching price data from Yahoo Finance..."):
        st.session_state.price_data = fetch_price_data(ETFs)

price_data = st.session_state.price_data

# ─── Fetch news ──────────────────────────────────────────────────────────
if refresh_news:
    with st.spinner("Searching news for all 12 ETFs... (30–60 seconds)"):
        try:
            st.session_state.news_data = fetch_news_and_sentiment(api_key)
            st.toast("News refreshed ✓", icon="✅")
        except Exception as e:
            st.error(f"News fetch failed: {e}")

# ─── Run analysis ────────────────────────────────────────────────────────
if run_analysis:
    if abs(total - 100.0) > 0.01:
        st.error("Allocations must total 100% before analysing.")
    else:
        with st.spinner("Generating portfolio analysis..."):
            try:
                st.session_state.analysis = generate_analysis(
                    api_key,
                    st.session_state.allocs,
                    st.session_state.news_data,
                    price_data,
                )
                st.toast("Analysis complete ✓", icon="✅")
            except Exception as e:
                st.error(f"Analysis failed: {e}")

news_data = st.session_state.news_data

# ─── Main layout ─────────────────────────────────────────────────────────
st.title("📊 ETF Sentiment Dashboard")
st.caption(f"Portfolio total: **{total:.1f}%** · {len(ETFs)} positions · Last updated {datetime.now().strftime('%H:%M %d %b %Y')}")

# ── Portfolio overview metrics ──
allocs = st.session_state.allocs
core_w = sum(v for t, v in allocs.items() if ETFs[t]["cat"] == "Core" and t != "CSH2")
sat_w  = sum(v for t, v in allocs.items() if ETFs[t]["cat"] == "Satellite")
cash_w = allocs.get("CSH2", 0)

c1, c2, c3, c4 = st.columns(4)
c1.metric("Core equity", f"{core_w:.0f}%")
c2.metric("Satellites",  f"{sat_w:.0f}%")
c3.metric("Cash buffer", f"{cash_w:.0f}%")
bullish_count = sum(1 for v in news_data.values() if v.get("sentiment") == "bullish")
c4.metric("Bullish positions", f"{bullish_count} / {len(news_data)}" if news_data else "—")

st.divider()

# ── Allocation donut chart ──
col_chart, col_analysis = st.columns([1, 1])

with col_chart:
    st.subheader("Allocation")
    colors = {
        "Core":      ["#378ADD", "#5090cc", "#6aa0dd", "#80b0ee", "#99c0f0", "#b0d0f5"],
        "Satellite": ["#1D9E75", "#2db888", "#45c89a", "#5dd8aa", "#75e8bb", "#8df8cc"],
    }
    tickers_sorted = list(allocs.keys())
    sizes  = [allocs[t] for t in tickers_sorted]
    labels = [f"{t} {allocs[t]}%" for t in tickers_sorted]
    clrs   = []
    cat_counts = {"Core": 0, "Satellite": 0}
    for t in tickers_sorted:
        cat = ETFs[t]["cat"]
        idx = cat_counts[cat] % len(colors[cat])
        clrs.append(colors[cat][idx])
        cat_counts[cat] += 1

    fig_donut = go.Figure(go.Pie(
        labels=labels, values=sizes,
        hole=0.55, marker_colors=clrs,
        textinfo="label", hovertemplate="%{label}<extra></extra>",
    ))
    fig_donut.update_layout(
        margin=dict(t=0, b=0, l=0, r=0),
        height=300,
        showlegend=False,
        annotations=[dict(text=f"{total:.0f}%", x=0.5, y=0.5,
                          font_size=20, showarrow=False)],
    )
    st.plotly_chart(fig_donut, use_container_width=True)

with col_analysis:
    st.subheader("Portfolio insights")
    if st.session_state.analysis:
        st.markdown(st.session_state.analysis)
    else:
        st.info("Click **Analyse portfolio** in the sidebar to generate insights.")

st.divider()

# ── Per-ETF cards ──
st.subheader("Per-ETF overview")

for cat in ["Core", "Satellite"]:
    st.caption(cat.upper())
    etfs_in_cat = [t for t, v in ETFs.items() if v["cat"] == cat]
    cols = st.columns(len(etfs_in_cat))

    for col, ticker in zip(cols, etfs_in_cat):
        info  = ETFs[ticker]
        pd_   = price_data.get(ticker)
        nd    = news_data.get(ticker, {})
        sent  = nd.get("sentiment", "")
        alloc = allocs[ticker]

        badge = {"bullish": "🟢", "neutral": "🟡", "bearish": "🔴"}.get(sent, "⚪")

        with col:
            st.markdown(f"**{ticker}**  {badge}")
            st.caption(info["name"])
            st.caption(f"Weight: **{alloc}%**")

            if pd_:
                ret_1w = pd_["ret_1w"]
                ret_1m = pd_["ret_1m"]
                color_1w = "normal" if ret_1w >= 0 else "inverse"
                color_1m = "normal" if ret_1m >= 0 else "inverse"
                st.metric("1W", f"{ret_1w:+.1f}%", delta_color=color_1w,
                          label_visibility="collapsed")
                st.caption(f"1M: {ret_1m:+.1f}%  3M: {pd_['ret_3m']:+.1f}%")
            else:
                st.caption("Price data unavailable")

            if nd:
                with st.expander("News"):
                    for item in nd.get("news", []):
                        st.markdown(f"• {item}")
                    if nd.get("drivers"):
                        st.caption(f"**Driver:** {nd['drivers']}")

st.divider()

# ── Price performance chart ──
st.subheader("3-month price performance (normalised to 100)")

tickers_with_data = [t for t in ETFs if price_data.get(t) is not None]

if tickers_with_data:
    selected = st.multiselect(
        "Select ETFs to compare",
        options=tickers_with_data,
        default=tickers_with_data[:6],
    )

    if selected:
        fig = go.Figure()
        palette = px.colors.qualitative.Set2
        for i, ticker in enumerate(selected):
            hist = price_data[ticker]["history"]
            # Normalise to 100
            base  = hist["price"].iloc[0]
            normd = hist["price"] / base * 100
            fig.add_trace(go.Scatter(
                x=hist["date"], y=normd,
                name=ticker,
                line=dict(color=palette[i % len(palette)], width=2),
                hovertemplate=f"{ticker}: %{{y:.1f}}<extra></extra>",
            ))
        fig.add_hline(y=100, line_dash="dot", line_color="grey", opacity=0.4)
        fig.update_layout(
            height=380,
            margin=dict(t=20, b=20),
            hovermode="x unified",
            legend=dict(orientation="h", y=-0.15),
            yaxis_title="Normalised price (base=100)",
            xaxis_title="",
        )
        st.plotly_chart(fig, use_container_width=True)
else:
    st.info("Click **↻ Prices** to load chart data.")

# ── News detail table ──
if news_data:
    st.divider()
    st.subheader("Sentiment summary")
    rows = []
    for ticker, nd in news_data.items():
        rows.append({
            "ETF":       ticker,
            "Name":      ETFs[ticker]["name"],
            "Sentiment": nd.get("sentiment", "—").capitalize(),
            "Key driver": nd.get("drivers", "—"),
        })
    df = pd.DataFrame(rows)

    def highlight_sentiment(val):
        colors = {"Bullish": "background-color:#e1f5ee; color:#0f6e56",
                  "Neutral": "background-color:#faeeda; color:#854f0b",
                  "Bearish": "background-color:#fcebeb; color:#a32d2d"}
        return colors.get(val, "")

    st.dataframe(
        df.style.applymap(highlight_sentiment, subset=["Sentiment"]),
        use_container_width=True,
        hide_index=True,
    )
