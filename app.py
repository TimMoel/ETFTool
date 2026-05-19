import streamlit as st
import yfinance as yf
import plotly.graph_objects as go
import plotly.express as px
import pandas as pd
import anthropic
import json
from datetime import datetime, timedelta

st.set_page_config(page_title="ETF Dashboard", page_icon="📊", layout="wide")

API_MIN_REFRESH_HRS   = 6
API_COST_PER_NEWS     = 0.01
API_COST_PER_ANALYSIS = 0.001

api_key = st.secrets["ANTHROPIC_API_KEY"]

st.markdown("""
<style>
[data-testid="stAppViewContainer"] { background: #f7f8fa; }
[data-testid="stSidebar"] { background: #ffffff; border-right: 1px solid #e8e8e8; }
[data-testid="metric-container"] { background:#ffffff; border:1px solid #eaeaea; border-radius:10px; padding:16px; }
.etf-card { background:#ffffff; border:1px solid #eaeaea; border-radius:10px; padding:14px 16px; margin-bottom:4px; }
.etf-card.buy  { border-left:4px solid #1D9E75; }
.etf-card.hold { border-left:4px solid #EF9F27; }
.etf-card.sell { border-left:4px solid #E24B4A; }
.rating-buy  { background:#e1f5ee; color:#0f6e56; padding:3px 10px; border-radius:5px; font-size:12px; font-weight:600; }
.rating-hold { background:#faeeda; color:#854f0b; padding:3px 10px; border-radius:5px; font-size:12px; font-weight:600; }
.rating-sell { background:#fcebeb; color:#a32d2d; padding:3px 10px; border-radius:5px; font-size:12px; font-weight:600; }
.sent-bullish { background:#e1f5ee; color:#0f6e56; padding:2px 8px; border-radius:4px; font-size:11px; }
.sent-neutral { background:#faeeda; color:#854f0b; padding:2px 8px; border-radius:4px; font-size:11px; }
.sent-bearish { background:#fcebeb; color:#a32d2d; padding:2px 8px; border-radius:4px; font-size:11px; }
.news-high   { background:#fff8f8; border-left:3px solid #E24B4A; border-radius:5px; padding:8px 10px; margin:4px 0; font-size:13px; }
.news-medium { background:#fffdf5; border-left:3px solid #EF9F27; border-radius:5px; padding:8px 10px; margin:4px 0; font-size:13px; }
.news-low    { background:#f9f9f9; border-left:3px solid #e0e0e0; border-radius:5px; padding:8px 10px; margin:4px 0; font-size:13px; }
.news-impact-high   { background:#fcebeb; color:#a32d2d; font-size:10px; font-weight:600; padding:1px 6px; border-radius:3px; margin-right:6px; }
.news-impact-medium { background:#faeeda; color:#854f0b; font-size:10px; font-weight:600; padding:1px 6px; border-radius:3px; margin-right:6px; }
.section-head { font-size:11px; font-weight:600; letter-spacing:0.07em; text-transform:uppercase; color:#999; margin:16px 0 8px; }
.cost-chip { background:#f0f0f0; border-radius:5px; padding:4px 10px; font-size:12px; color:#666; display:inline-block; margin:2px; }
.ticker-label { font-size:15px; font-weight:600; color:#1a1a1a; }
.etf-name-label { font-size:12px; color:#888; margin-bottom:8px; }
.alloc-pct { font-size:20px; font-weight:600; color:#1a1a1a; }
.ret-pos { color:#0f6e56; font-weight:500; font-size:13px; }
.ret-neg { color:#a32d2d; font-weight:500; font-size:13px; }
.ret-neu { color:#888; font-size:13px; }
</style>
""", unsafe_allow_html=True)

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

if "etfs"            not in st.session_state: st.session_state.etfs = DEFAULT_ETFS.copy()
if "allocs"          not in st.session_state: st.session_state.allocs = DEFAULT_ALLOCS.copy()
if "news_data"       not in st.session_state: st.session_state.news_data = {}
if "analysis"        not in st.session_state: st.session_state.analysis = ""
if "price_data"      not in st.session_state: st.session_state.price_data = {}
if "last_news_fetch" not in st.session_state: st.session_state.last_news_fetch = None
if "api_spend"       not in st.session_state: st.session_state.api_spend = 0.0

def hours_since_last_fetch():
    if not st.session_state.last_news_fetch: return None
    return (datetime.now() - st.session_state.last_news_fetch).total_seconds() / 3600

@st.cache_data(ttl=900)
def fetch_price_data(etf_pairs):
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
    with client.messages.stream(
        model="claude-opus-4-5-20251101", max_tokens=4000,
        tools=[{{"type":"web_search_20250305","name":"web_search"}}],
        messages=[{{"role":"user","content":prompt}}],
        betas=["web-search-2025-03-05"],
    ) as stream:
        text = stream.get_final_text()
    clean = text.replace("```json","").replace("```","").strip()
    return json.loads(clean[clean.index("{"):clean.rindex("}")+1])

def generate_analysis(allocs, news, price_data, etfs):
    client = anthropic.Anthropic(api_key=api_key)
    alloc_str  = ", ".join(f"{t} {v}%" for t,v in allocs.items())
    price_str  = "".join(f"{t}: 1W={d['ret_1w']:+.1f}% 1M={d['ret_1m']:+.1f}% 3M={d['ret_3m']:+.1f}%\n" for t,d in price_data.items() if d)
    sell_list  = [t for t,v in news.items() if v.get("rating")=="sell"]
    buy_list   = [t for t,v in news.items() if v.get("rating")=="buy"]
    high_news  = [(t,i["text"]) for t,v in news.items() for i in v.get("news",[]) if isinstance(i,dict) and i.get("impact")=="high"]
    msg = client.messages.create(
        model="claude-opus-4-5-20251101", max_tokens=1500,
        messages=[{"role":"user","content":
            f"Portfolio analyst. Allocation: {alloc_str}\nPrice: {price_str}\n"
            f"Buy signals: {buy_list}\nSell signals: {sell_list}\nHigh-impact news: {high_news}\n"
            f"Full data: {json.dumps(news)}\n\n"
            "Write 3 paragraphs: (1) overall health vs momentum and ratings, "
            "(2) immediate attention items, (3) top 3 watch items with one-line action each. "
            "Be specific, reference tickers and numbers. No bullets. No preamble."}],
    )
    return msg.content[0].text

# ─── SIDEBAR ──────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("### 📊 ETF Dashboard")
    st.divider()

    hrs = hours_since_last_fetch()
    can_refresh = hrs is None or hrs >= API_MIN_REFRESH_HRS
    next_refresh_msg = "" if can_refresh else f"Next free refresh in {API_MIN_REFRESH_HRS-hrs:.1f}h"

    with st.expander("💳 API credits", expanded=False):
        st.markdown(f"""
        <span class="cost-chip">Session: ~${st.session_state.api_spend:.3f}</span>
        <span class="cost-chip">News: ~${API_COST_PER_NEWS}</span>
        <span class="cost-chip">Analysis: ~${API_COST_PER_ANALYSIS}</span>
        """, unsafe_allow_html=True)
        if st.session_state.last_news_fetch:
            st.caption(f"Last fetch: {st.session_state.last_news_fetch.strftime('%H:%M %d %b')}")
        if not can_refresh:
            st.caption(f"⏳ {next_refresh_msg}")
        st.caption("Minimum 6h between refreshes to protect credits.")

    st.divider()
    st.markdown('<div class="section-head">Allocations</div>', unsafe_allow_html=True)
    total = 0.0
    new_allocs = {}
    for cat in ["Core","Satellite"]:
        st.caption(cat)
        for ticker, info in st.session_state.etfs.items():
            if info["cat"] == cat:
                val = st.number_input(
                    f"{ticker} — {info['name']}",
                    min_value=0.0, max_value=100.0, step=0.5,
                    value=float(st.session_state.allocs.get(ticker, 0.0)),
                    key=f"alloc_{ticker}",
                )
                new_allocs[ticker] = val
                total += val
    st.session_state.allocs = new_allocs
    delta = total - 100.0
    if abs(delta) < 0.01: st.success(f"Total: {total:.1f}% ✓")
    else: st.error(f"Total: {total:.1f}% ({delta:+.1f}%)")

    st.divider()
    st.markdown('<div class="section-head">Add ETF</div>', unsafe_allow_html=True)
    ca, cb = st.columns(2)
    with ca: new_ticker = st.text_input("Ticker", placeholder="IWDG", key="new_ticker").upper().strip()
    with cb: new_name   = st.text_input("Name",   placeholder="Clean Energy", key="new_name")
    new_cat = st.selectbox("Category", ["Core","Satellite"], key="new_cat")
    if st.button("➕ Add ETF", use_container_width=True):
        if new_ticker and new_name:
            if new_ticker in st.session_state.etfs:
                st.warning(f"{new_ticker} already exists.")
            else:
                st.session_state.etfs[new_ticker] = {"name":new_name,"yahoo":f"{new_ticker}.L","cat":new_cat}
                st.session_state.allocs[new_ticker] = 0.0
                st.success(f"Added {new_ticker}"); st.rerun()
        else: st.warning("Enter ticker and name.")

    st.markdown('<div class="section-head">Remove ETF</div>', unsafe_allow_html=True)
    rm = st.selectbox("Select to remove", ["—"]+list(st.session_state.etfs.keys()), key="rm_sel")
    if st.button("🗑 Remove", use_container_width=True):
        if rm != "—":
            for d in [st.session_state.etfs, st.session_state.allocs, st.session_state.news_data, st.session_state.price_data]:
                d.pop(rm, None)
            st.success(f"Removed {rm}"); st.rerun()

    st.divider()
    c1s, c2s = st.columns(2)
    with c1s: refresh_prices   = st.button("↻ Prices", use_container_width=True)
    with c2s: refresh_news_btn = st.button("↻ News", use_container_width=True, disabled=not can_refresh, help=next_refresh_msg)
    force_refresh = False
    if not can_refresh:
        force_refresh = st.button(f"⚠ Force refresh (~${API_COST_PER_NEWS})", use_container_width=True)
    run_analysis = st.button("Analyse portfolio ↗", use_container_width=True, type="primary")

# ─── DATA ─────────────────────────────────────────────────────────────────────
etf_pairs = tuple((t, v["yahoo"]) for t, v in st.session_state.etfs.items())
if refresh_prices or not st.session_state.price_data:
    with st.spinner("Fetching prices..."):
        st.session_state.price_data = fetch_price_data(etf_pairs)

if refresh_news_btn or force_refresh:
    with st.spinner("Searching news and ratings... (30–60 seconds)"):
        try:
            st.session_state.news_data = fetch_news_and_ratings(st.session_state.etfs)
            st.session_state.last_news_fetch = datetime.now()
            st.session_state.api_spend += API_COST_PER_NEWS
            st.toast("News refreshed ✓", icon="✅")
        except Exception as e:
            st.error(f"News fetch failed: {e}")

if run_analysis:
    if abs(total-100.0) > 0.01: st.error("Allocations must total 100%.")
    else:
        with st.spinner("Generating analysis..."):
            try:
                st.session_state.analysis = generate_analysis(
                    st.session_state.allocs, st.session_state.news_data,
                    st.session_state.price_data, st.session_state.etfs)
                st.session_state.api_spend += API_COST_PER_ANALYSIS
                st.toast("Analysis complete ✓", icon="✅")
            except Exception as e: st.error(f"Analysis failed: {e}")

price_data = st.session_state.price_data
news_data  = st.session_state.news_data
allocs     = st.session_state.allocs
etfs       = st.session_state.etfs

# ─── MAIN ─────────────────────────────────────────────────────────────────────
st.markdown("## 📊 ETF Sentiment Dashboard")
st.caption(f"**{len(etfs)} positions** · Total: **{total:.1f}%** · {datetime.now().strftime('%H:%M, %d %b %Y')}")

core_w = sum(v for t,v in allocs.items() if etfs.get(t,{}).get("cat")=="Core" and t!="CSH2")
sat_w  = sum(v for t,v in allocs.items() if etfs.get(t,{}).get("cat")=="Satellite")
cash_w = allocs.get("CSH2",0)
buy_ct = sum(1 for v in news_data.values() if v.get("rating")=="buy")
sell_ct= sum(1 for v in news_data.values() if v.get("rating")=="sell")

c1,c2,c3,c4,c5 = st.columns(5)
c1.metric("Core equity",  f"{core_w:.0f}%")
c2.metric("Satellites",   f"{sat_w:.0f}%")
c3.metric("Cash buffer",  f"{cash_w:.0f}%")
c4.metric("Buy signals",  f"{buy_ct}"  if news_data else "—")
c5.metric("Sell signals", f"{sell_ct}" if news_data else "—")

st.divider()

col_l, col_r = st.columns([1,1])
with col_l:
    st.markdown("#### Allocation")
    blues  = ["#378ADD","#5090cc","#6aa0dd","#80b0ee","#99c0f0","#b0d0f5"]
    greens = ["#1D9E75","#2db888","#45c89a","#5dd8aa","#75e8bb","#8df8cc"]
    labels = [f"{t}  {v}%" for t,v in allocs.items()]
    values = list(allocs.values())
    colors = [blues[i%6] if etfs.get(t,{}).get("cat")=="Core" else greens[i%6] for i,t in enumerate(allocs)]
    fig_d = go.Figure(go.Pie(
        labels=labels, values=values, hole=0.6, marker=dict(colors=colors, line=dict(color="#fff",width=2)),
        textinfo="none", hovertemplate="%{label}<extra></extra>",
    ))
    fig_d.update_layout(
        margin=dict(t=0,b=0,l=0,r=0), height=280, showlegend=False,
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        annotations=[dict(text=f"{total:.0f}%",x=0.5,y=0.5,font=dict(size=22,color="#1a1a1a"),showarrow=False)],
    )
    st.plotly_chart(fig_d, use_container_width=True)

with col_r:
    st.markdown("#### Portfolio insights")
    if st.session_state.analysis:
        st.markdown(st.session_state.analysis)
    else:
        st.info("Click **Analyse portfolio** in the sidebar to generate AI-powered insights.")

st.divider()

def ret_html(v, lbl):
    if v is None: return f'<span class="ret-neu">— {lbl}</span>'
    cls = "ret-pos" if v >= 0 else "ret-neg"
    return f'<span class="{cls}">{v:+.1f}% {lbl}</span>'

def rating_html(r):
    cls = {"buy":"rating-buy","hold":"rating-hold","sell":"rating-sell"}.get(r,"rating-hold")
    return f'<span class="{cls}">{(r or "—").upper()}</span>'

def sent_html(s):
    cls = {"bullish":"sent-bullish","neutral":"sent-neutral","bearish":"sent-bearish"}.get(s,"sent-neutral")
    return f'<span class="{cls}">{(s or "—").capitalize()}</span>'

for cat in ["Core","Satellite"]:
    st.markdown(f'<div class="section-head">{cat} positions</div>', unsafe_allow_html=True)
    cat_etfs = [(t,i) for t,i in etfs.items() if i["cat"]==cat]
    cols = st.columns(min(len(cat_etfs),4))
    for idx,(ticker,info) in enumerate(cat_etfs):
        pd_  = price_data.get(ticker)
        nd   = news_data.get(ticker,{})
        rating = nd.get("rating","")
        sent   = nd.get("sentiment","")
        alloc_v= allocs.get(ticker,0)
        card_cls = f"etf-card {rating}" if rating in ("buy","hold","sell") else "etf-card"
        with cols[idx%4]:
            st.markdown(f"""
            <div class="{card_cls}">
              <div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:4px">
                <div><span class="ticker-label">{ticker}</span>
                     <div class="etf-name-label">{info['name']}</div></div>
                <div style="text-align:right">{rating_html(rating)}<div style="margin-top:4px">{sent_html(sent)}</div></div>
              </div>
              <div class="alloc-pct">{alloc_v:.1f}%</div>
              <div style="margin-top:6px;display:flex;gap:10px;flex-wrap:wrap">
                {ret_html(pd_['ret_1w'] if pd_ else None,'1W')}
                {ret_html(pd_['ret_1m'] if pd_ else None,'1M')}
                {ret_html(pd_['ret_3m'] if pd_ else None,'3M')}
              </div>
            </div>""", unsafe_allow_html=True)
            if nd:
                analyst = nd.get("analyst_view","")
                with st.expander("News & signals"):
                    if analyst: st.markdown(f"**Analyst view:** {analyst}")
                    for item in nd.get("news",[]):
                        impact = item.get("impact","low") if isinstance(item,dict) else "low"
                        text   = item.get("text",item)   if isinstance(item,dict) else item
                        badge  = f'<span class="news-impact-{impact}">{impact.upper()}</span>' if impact in ("high","medium") else ""
                        st.markdown(f'<div class="news-{impact}">{badge}{text}</div>', unsafe_allow_html=True)
                    if nd.get("drivers"): st.caption(f"📌 {nd['drivers']}")

st.divider()
st.markdown("#### 3-month performance (normalised to 100)")
tickers_with_data = [t for t in etfs if price_data.get(t)]
if tickers_with_data:
    selected = st.multiselect("Compare ETFs", tickers_with_data, default=tickers_with_data[:6])
    if selected:
        palette = px.colors.qualitative.Set2
        fig_l = go.Figure()
        for i,ticker in enumerate(selected):
            hist = price_data[ticker]["history"]
            norm = hist["price"] / hist["price"].iloc[0] * 100
            fig_l.add_trace(go.Scatter(
                x=hist["date"], y=norm.round(2), name=ticker,
                line=dict(color=palette[i%len(palette)],width=2),
                hovertemplate=f"{ticker}: %{{y:.1f}}<extra></extra>",
            ))
        fig_l.add_hline(y=100, line_dash="dot", line_color="#cccccc")
        fig_l.update_layout(
            height=340, paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="#ffffff",
            margin=dict(t=10,b=10), hovermode="x unified",
            legend=dict(orientation="h",y=-0.2,font=dict(size=11)),
            xaxis=dict(gridcolor="#f0f0f0",tickfont=dict(size=11)),
            yaxis=dict(gridcolor="#f0f0f0",tickfont=dict(size=11),title="Price (base=100)"),
        )
        st.plotly_chart(fig_l, use_container_width=True)
else:
    st.info("Click **↻ Prices** to load chart data.")

if news_data:
    high_items = [(t, i["text"] if isinstance(i,dict) else i)
                  for t,v in news_data.items()
                  for i in v.get("news",[])
                  if (i.get("impact") if isinstance(i,dict) else "")=="high"]
    if high_items:
        st.divider()
        st.markdown("#### 🔴 High-impact news")
        for ticker, text in high_items:
            st.markdown(f'<div class="news-high" style="margin-bottom:6px"><strong>{ticker}</strong> — {text}</div>',
                        unsafe_allow_html=True)

    st.divider()
    st.markdown("#### Ratings & sentiment summary")
    rows = [{"ETF":t,"Name":etfs.get(t,{}).get("name",""),
             "Rating":(v.get("rating") or "—").capitalize(),
             "Sentiment":(v.get("sentiment") or "—").capitalize(),
             "Key driver":v.get("drivers","—")}
            for t,v in news_data.items()]
    df = pd.DataFrame(rows)
    def style_r(val):
        return {"Buy":"background-color:#e1f5ee;color:#0f6e56","Hold":"background-color:#faeeda;color:#854f0b","Sell":"background-color:#fcebeb;color:#a32d2d"}.get(val,"")
    def style_s(val):
        return {"Bullish":"background-color:#e1f5ee;color:#0f6e56","Neutral":"background-color:#faeeda;color:#854f0b","Bearish":"background-color:#fcebeb;color:#a32d2d"}.get(val,"")
    st.dataframe(df.style.applymap(style_r,subset=["Rating"]).applymap(style_s,subset=["Sentiment"]),
                 use_container_width=True, hide_index=True)
