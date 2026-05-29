"""
Headless nightly refresh for ETFTool.

Run by GitHub Actions (or manually) after market close. Fetches fresh
prices + news, computes signals, writes today's snapshot to SQLite, and
sends a Telegram message summarising what changed.

Environment variables (read from os.environ; GitHub secrets supply them
in the workflow):

    ANTHROPIC_API_KEY    required for news fetch
    TELEGRAM_BOT_TOKEN   optional — skip alerts if missing
    TELEGRAM_CHAT_ID     optional — skip alerts if missing
"""

import os
import sys
import json
from datetime import datetime

import requests

import core
import db
import signals as sg


# Hard-coded universe — must match the one in app.py.
ETFS = {
    "VWRP": {"name": "Global all-world",  "yahoo": "VWRP.L"},
    "XMWX": {"name": "Developed ex-US",   "yahoo": "XMWX.L"},
    "EMIM": {"name": "Emerging markets",  "yahoo": "EMIM.L"},
    "CSH2": {"name": "Cash/overnight",    "yahoo": "CSH2.L"},
    "SPDR": {"name": "S&P 500 UCITS",     "yahoo": "SPDR.L"},
    "VEUR": {"name": "Europe",            "yahoo": "VEUR.L"},
    "NATP": {"name": "Defence global",    "yahoo": "NATP.L"},
    "NUCG": {"name": "Nuclear/uranium",   "yahoo": "NUCG.L"},
    "WDEP": {"name": "Defence Europe",    "yahoo": "WDEP.L"},
    "BUGG": {"name": "Cybersecurity",     "yahoo": "BUGG.L"},
    "ARMG": {"name": "Defence tech",      "yahoo": "ARMG.L"},
    "RBTX": {"name": "Robotics",          "yahoo": "RBTX.L"},
}


def send_telegram(token, chat_id, text):
    """Post a Markdown message to a Telegram chat. Best-effort, swallows errors."""
    if not token or not chat_id:
        return
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": text,
                  "parse_mode": "Markdown", "disable_web_page_preview": True},
            timeout=15,
        )
        if r.status_code >= 400:
            print(f"telegram error {r.status_code}: {r.text}", file=sys.stderr)
    except Exception as e:
        print(f"telegram exception: {e}", file=sys.stderr)


def format_changes_message(changes):
    """Convert db.diff_vs_previous() output to a Telegram-friendly Markdown string."""
    if not changes:
        return None
    lines = ["*ETF Tracker · daily update*", ""]
    by_kind = {"rating": [], "high": [], "low": [], "signal": []}
    for c in changes:
        by_kind.setdefault(c["kind"], []).append(c)

    sev_icon = {"up": "🟢", "down": "🔴", "neutral": "🟡"}

    if by_kind["rating"]:
        lines.append("*Rating changes*")
        for c in by_kind["rating"]:
            lines.append(f"{sev_icon.get(c['severity'], '•')} `{c['ticker']}` — {c['detail']}")
        lines.append("")

    if by_kind["high"] or by_kind["low"]:
        lines.append("*New highs / lows*")
        for c in by_kind["high"] + by_kind["low"]:
            lines.append(f"{sev_icon.get(c['severity'], '•')} `{c['ticker']}` — {c['detail']}")
        lines.append("")

    if by_kind["signal"]:
        lines.append("*Signal flips*")
        for c in by_kind["signal"]:
            lines.append(f"{sev_icon.get(c['severity'], '•')} `{c['ticker']}` — {c['detail']}")
        lines.append("")

    lines.append(f"_run {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}_")
    return "\n".join(lines)


def main():
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    news_enabled = os.environ.get("ENABLE_NEWS", "").lower() in ("1", "true", "yes")
    if news_enabled and not api_key:
        print("ERROR: ENABLE_NEWS=1 but ANTHROPIC_API_KEY not set", file=sys.stderr)
        return 1

    print("Fetching prices…")
    etf_pairs = tuple((t, v["yahoo"]) for t, v in ETFS.items())
    price_data = core.fetch_price_data_raw(etf_pairs)
    print(f"  prices: {sum(1 for v in price_data.values() if v)} / {len(ETFS)} ETFs")

    if news_enabled:
        print("Fetching news (ENABLE_NEWS=1)…")
        try:
            news_data = core.fetch_news_and_ratings_raw(ETFS, api_key)
        except Exception as e:
            print(f"  news fetch failed: {e}", file=sys.stderr)
            news_data = {t: {"rating": "hold", "sentiment": "neutral", "news": []}
                         for t in ETFS}
    else:
        print("News fetch disabled (set ENABLE_NEWS=1 to re-enable). "
              "Snapshots will use rating=hold; alerts will only fire on "
              "price-driven signals (MA crosses, new highs/lows).")
        news_data = {t: {"rating": "hold", "sentiment": "neutral", "news": []}
                     for t in ETFS}

    print("Computing signals + writing snapshots…")
    db.init_db()
    for ticker, pd_ in price_data.items():
        if not pd_:
            continue
        flags = sg.compute_signals(pd_.get("history"),
                                   fundamentals=pd_,
                                   volume_series=pd_.get("volume"))
        rating = (news_data.get(ticker) or {}).get("rating", "hold")
        score = sg.composite_score(rating, flags)
        db.insert_snapshot(ticker, {
            "price": pd_.get("current"),
            "ret_1w": pd_.get("ret_1w"),
            "ret_1m": pd_.get("ret_1m"),
            "ret_3m": pd_.get("ret_3m"),
            "drawdown": pd_.get("drawdown"),
            "vol_30d": pd_.get("vol_30d"),
            "beta": pd_.get("beta"),
            "dividend_yield": pd_.get("dividend_yield"),
            "rating": rating,
            "sentiment": (news_data.get(ticker) or {}).get("sentiment"),
            "score": score,
            "signals": flags,
        })

    print("Diffing against previous snapshot…")
    changes = db.diff_vs_previous()
    print(f"  {len(changes)} change(s)")
    for c in changes:
        print(f"    {c['ticker']} · {c['kind']} · {c['severity']} · {c['detail']}")

    msg = format_changes_message(changes)
    if msg:
        send_telegram(os.environ.get("TELEGRAM_BOT_TOKEN"),
                      os.environ.get("TELEGRAM_CHAT_ID"),
                      msg)
        print("  telegram message sent")
    else:
        print("  no changes — no telegram message sent")

    return 0


if __name__ == "__main__":
    sys.exit(main())
