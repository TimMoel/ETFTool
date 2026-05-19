# ETF Sentiment Dashboard

Interactive portfolio dashboard with live price data, news sentiment and Claude-powered analysis.

## What it does

- **Live price data** — pulls 3-month history from Yahoo Finance for all 12 ETFs
- **News sentiment** — Claude searches current news and returns bullish/neutral/bearish per ETF
- **Portfolio analysis** — Claude synthesises allocation + price momentum + news into actionable insights
- **Performance chart** — normalised 3-month chart with multi-ETF comparison
- **Editable allocations** — change any weight in the sidebar, analysis updates accordingly

## Run locally (2 minutes)

```bash
pip install -r requirements.txt
streamlit run app.py
```

Then open http://localhost:8501

Enter your Anthropic API key in the sidebar (from console.anthropic.com).

## Deploy to Streamlit Cloud (free, 5 minutes)

1. Push this folder to a GitHub repo
2. Go to share.streamlit.io
3. Connect your GitHub repo
4. Set `ANTHROPIC_API_KEY` in Secrets:
   ```toml
   ANTHROPIC_API_KEY = "sk-ant-..."
   ```
5. Deploy — you get a public URL instantly

## Using secrets in Streamlit Cloud

When deployed, replace the API key input with:
```python
api_key = st.secrets["ANTHROPIC_API_KEY"]
```

## Your ETFs

| Ticker | Name | Yahoo ticker | Default % |
|--------|------|-------------|-----------|
| VWRP | Global all-world | VWRP.L | 47% |
| XMWX | Developed ex-US | XMWX.L | 10% |
| EMIM | Emerging markets | EMIM.L | 10% |
| CSH2 | Cash/overnight | CSH2.L | 5% |
| SPDR | S&P 500 UCITS | SPDR.L | 6% |
| VEUR | Europe | VEUR.L | 4% |
| NATP | Defence global | NATP.L | 3% |
| NUCG | Nuclear/uranium | NUCG.L | 3% |
| WDEP | Defence Europe | WDEP.L | 3% |
| BUGG | Cybersecurity | BUGG.L | 3% |
| ARMG | Defence tech | ARMG.L | 3% |
| RBTX | Robotics | RBTX.L | 3% |

## Costs

- Streamlit Cloud: free
- Yahoo Finance: free (no API key needed)
- Claude API: ~£0.01 per news refresh, ~£0.001 per analysis
