"""
Pure data-fetch core for ETFTool.

No Streamlit, no caching, no UI side effects. Imported by both `app.py`
(wrapped with @st.cache_data + UI error handling) and `refresh_job.py`
(headless nightly run).
"""

import json
from datetime import datetime, timedelta

import anthropic
import pandas as pd
import yfinance as yf


def fetch_price_data_raw(etf_pairs):
    """
    Fetch ~260 trading days of price history + fundamentals per ETF.
    `etf_pairs` is an iterable of (ticker, yahoo_symbol).
    Returns {ticker: {...} | None}.
    """
    results = {}
    end = datetime.today()
    start = end - timedelta(days=400)
    for ticker, yahoo in etf_pairs:
        try:
            raw = yf.download(yahoo, start=start, end=end,
                              progress=False, auto_adjust=True)
            if raw.empty:
                results[ticker] = None
                continue
            if isinstance(raw.columns, pd.MultiIndex):
                raw.columns = raw.columns.get_level_values(0)
            close = raw["Close"].dropna()
            volume = raw["Volume"].dropna() if "Volume" in raw.columns else None
            if len(close) < 2:
                results[ticker] = None
                continue
            now = float(close.iloc[-1])
            w1 = float(close.iloc[-6]) if len(close) >= 6 else now
            m1 = float(close.iloc[-22]) if len(close) >= 22 else now
            m3 = float(close.iloc[-66]) if len(close) >= 66 else now
            vol_30d = (float(close.pct_change().tail(22).std() * (252 ** 0.5) * 100)
                       if len(close) >= 5 else None)
            entry = {
                "current": now,
                "ret_1w": (now - w1) / w1 * 100,
                "ret_1m": (now - m1) / m1 * 100,
                "ret_3m": (now - m3) / m3 * 100,
                "history": pd.DataFrame({"date": close.index, "price": close.values}),
                "volume": pd.Series(volume.values, index=volume.index) if volume is not None else None,
                "vol_30d": vol_30d,
                "high_52w": None, "low_52w": None, "drawdown": None,
                "year_change": None, "avg_volume_3m": None,
                "beta": None, "dividend_yield": None,
            }
            try:
                fi = yf.Ticker(yahoo).fast_info
                h52 = getattr(fi, "fifty_two_week_high", None)
                l52 = getattr(fi, "fifty_two_week_low", None)
                entry["high_52w"] = float(h52) if h52 else None
                entry["low_52w"] = float(l52) if l52 else None
                entry["drawdown"] = (now / h52 - 1) * 100 if h52 else None
                yc = getattr(fi, "year_change", None)
                entry["year_change"] = float(yc) * 100 if yc is not None else None
                av = getattr(fi, "three_month_average_volume", None)
                entry["avg_volume_3m"] = int(av) if av else None
                info = yf.Ticker(yahoo).info
                entry["beta"] = info.get("beta")
                dy = info.get("dividendYield")
                entry["dividend_yield"] = float(dy) * 100 if dy else None
            except Exception:
                pass
            results[ticker] = entry
        except Exception:
            results[ticker] = None
    return results


def fetch_news_and_ratings_raw(etfs, api_key):
    """
    Headless news/rating fetch using Claude Haiku + web search.
    `etfs` is the same {ticker: {...}} dict the app uses.
    Returns {ticker: {sentiment, rating, news, drivers, ...}} or raises.
    """
    client = anthropic.Anthropic(api_key=api_key)
    tickers_str = ", ".join(f"{t} ({v['name']})" for t, v in etfs.items())
    user_msg = {
        "role": "user",
        "content": (
            f"Search the web for recent news and market sentiment for these UK ETFs: {tickers_str}.\n"
            "Do at most 5 searches total — batch by theme (e.g. global equities, "
            "emerging markets, defence/thematic).\n\n"
            "Then return ONLY a raw JSON object (no markdown, no preamble):\n"
            "{\n"
            '  "TICKER": {\n'
            '    "sentiment": "bullish" | "neutral" | "bearish",\n'
            '    "rating": "buy" | "hold" | "sell",\n'
            '    "analyst_view": "brief analyst view or empty string",\n'
            '    "news": [\n'
            '      {"text": "headline", "impact": "high" | "medium" | "low", '
            '"source": "Publication", "url": "https://url-or-empty"}\n'
            "    ],\n"
            '    "drivers": "one sentence key driver"\n'
            "  }\n"
            "}\n"
            "Cover every ticker. Raw JSON only — your entire reply must be parseable JSON."
        ),
    }
    tools = [{"type": "web_search_20260209", "name": "web_search", "max_uses": 5}]
    model = "claude-sonnet-4-6"
    messages = [user_msg]
    response = client.messages.create(model=model, max_tokens=3000,
                                      tools=tools, messages=messages)
    while response.stop_reason == "pause_turn":
        messages = messages + [{"role": "assistant", "content": response.content}]
        response = client.messages.create(model=model, max_tokens=3000,
                                          tools=tools, messages=messages)
    text = next((b.text for b in response.content
                 if hasattr(b, "text") and b.text.strip()), "")
    if not text:
        raise ValueError("No text block in Claude response")
    clean = text.replace("```json", "").replace("```", "").strip()
    start = clean.index("{")
    end = clean.rindex("}") + 1
    return json.loads(clean[start:end])
