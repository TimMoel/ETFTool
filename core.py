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
            if len(close) < 2:
                results[ticker] = None
                continue

            # Detect Yahoo's GBp (pence) quote convention and convert to GBP.
            # LSE-listed ETFs are usually quoted in pence (e.g. 9023 = £90.23).
            # Without this fix, prices and any user-entered cost basis would be
            # off by 100x.
            divisor = 1.0
            ccy = None
            try:
                ccy = getattr(yf.Ticker(yahoo).fast_info, "currency", None)
            except Exception:
                pass
            if ccy and str(ccy).lower() == "gbp" and close.iloc[-1] > 1000:
                # Some Yahoo records label LSE pence as "GBP" but the price
                # magnitude betrays it — guard with a magnitude check.
                divisor = 100.0
            elif ccy and str(ccy) == "GBp":
                divisor = 100.0

            close = close / divisor
            open_  = (raw["Open"]  / divisor).reindex(close.index)
            high   = (raw["High"]  / divisor).reindex(close.index)
            low    = (raw["Low"]   / divisor).reindex(close.index)
            volume = raw["Volume"].reindex(close.index) if "Volume" in raw.columns else None

            now = float(close.iloc[-1])
            w1 = float(close.iloc[-6]) if len(close) >= 6 else now
            m1 = float(close.iloc[-22]) if len(close) >= 22 else now
            m3 = float(close.iloc[-66]) if len(close) >= 66 else now
            vol_30d = (float(close.pct_change().tail(22).std() * (252 ** 0.5) * 100)
                       if len(close) >= 5 else None)

            history_df = pd.DataFrame({
                "date":   close.index,
                "open":   open_.values,
                "high":   high.values,
                "low":    low.values,
                "price":  close.values,  # keep "price" for backward compat
                "volume": (volume.values if volume is not None else [0] * len(close)),
            })

            entry = {
                "current": now,
                "ret_1w": (now - w1) / w1 * 100,
                "ret_1m": (now - m1) / m1 * 100,
                "ret_3m": (now - m3) / m3 * 100,
                "history": history_df,
                "volume": pd.Series(volume.values, index=volume.index) if volume is not None else None,
                "vol_30d": vol_30d,
                "currency": "GBP" if divisor == 100.0 else (ccy or "GBP"),
                "high_52w": None, "low_52w": None, "drawdown": None,
                "year_change": None, "avg_volume_3m": None,
                "beta": None, "dividend_yield": None,
            }
            try:
                fi = yf.Ticker(yahoo).fast_info
                h52 = getattr(fi, "fifty_two_week_high", None)
                l52 = getattr(fi, "fifty_two_week_low", None)
                entry["high_52w"] = float(h52) / divisor if h52 else None
                entry["low_52w"]  = float(l52) / divisor if l52 else None
                entry["drawdown"] = (now / entry["high_52w"] - 1) * 100 if entry["high_52w"] else None
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
            "Do at most 3 searches total — batch by theme (e.g. global equities, "
            "emerging markets, defence/thematic).\n\n"
            "Then return ONLY a raw JSON object (no markdown, no preamble):\n"
            "{\n"
            '  "TICKER": {\n'
            '    "sentiment": "bullish" | "neutral" | "bearish",\n'
            '    "rating": "buy" | "hold" | "sell",\n'
            '    "news": [\n'
            '      {"text": "headline", "impact": "high" | "medium" | "low", '
            '"source": "Publication", "url": "https://url-or-empty"}\n'
            "    ],\n"
            '    "drivers": "one sentence key driver"\n'
            "  }\n"
            "}\n"
            "Cover every ticker. Up to 3 news items per ticker (most important only). "
            "Raw JSON only — your entire reply must be parseable JSON."
        ),
    }
    tools = [{"type": "web_search_20260209", "name": "web_search", "max_uses": 3}]
    model = "claude-sonnet-4-6"
    messages = [user_msg]
    response = client.messages.create(model=model, max_tokens=3500,
                                      tools=tools, messages=messages)
    while response.stop_reason == "pause_turn":
        messages = messages + [{"role": "assistant", "content": response.content}]
        response = client.messages.create(model=model, max_tokens=3500,
                                          tools=tools, messages=messages)
    text = next((b.text for b in response.content
                 if hasattr(b, "text") and b.text.strip()), "")
    if not text:
        raise ValueError(
            f"Claude returned no text block (stop_reason={response.stop_reason}). "
            "Likely all tokens consumed by tool use — raise max_tokens."
        )
    clean = text.replace("```json", "").replace("```", "").strip()
    try:
        start = clean.index("{")
        end = clean.rindex("}") + 1
        return json.loads(clean[start:end])
    except (ValueError, json.JSONDecodeError) as e:
        snippet = clean[:200] + ("…" if len(clean) > 200 else "")
        raise ValueError(
            f"News JSON parse failed ({type(e).__name__}: {e}). "
            f"Response start: {snippet!r}"
        ) from e
