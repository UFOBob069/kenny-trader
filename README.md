# VWAP Event Trading Copilot

Kenny Glick-style VWAP event trading: scan earnings/news movers, detect
fakeout-shakeout-breakout ("faux show bro") longs and VWAP-breakdown shorts,
score every signal with an AI confidence engine, then either alert for manual
approval or auto-execute through Interactive Brokers.

> **This trades real money if you point it at a live account. It defaults to
> the IBKR paper port (7497) with auto-trading OFF. Keep it that way until the
> signal quality has earned your trust.**

## How it works

```
FMP earnings calendar + watchlist
        │
        ▼
   Scanner ── filters: |gap| ≥ 8%, rvol ≥ 3x, price ≥ $5, catalyst exists
        │
        ▼
   IBKR 1-min bars (incl. extended hours)
        │
        ▼
   SetupDetector ── per symbol, tracks:
        blue line   = today's session VWAP
        yellow line = prior-day-anchored VWAP (keeps accumulating today)
        LONG  : break low → recover low → reclaim VWAP   (stop = fakeout low, target = HOD)
        SHORT : extended above VWAP → lose VWAP          (stop = HOD, target = prior-day VWAP)
        │
        ▼
   Confidence engine (0–100)
        45% technical  (pattern, VWAP/PDV position, rvol, gap, reward:risk)
        25% fundamental (EPS/revenue beat or miss from FMP)
        30% AI catalyst read (OpenAI on earnings + headlines)
        │
        ├── confidence ≥ threshold AND auto-trade on → bracket order via IBKR
        └── otherwise → pending signal in the dashboard (Buy / Ignore)
```

Risk manager enforces: max trades/day, max daily loss, $ risk per trade,
max position notional. Position size = risk_per_trade ÷ (entry − stop).

## Setup

1. **Python 3.11+**, then:
   ```
   python -m venv .venv
   .venv\Scripts\activate
   pip install -r requirements.txt
   ```
2. Copy `.env.example` to `.env` and fill in your keys
   (FMP, OpenAI, Supabase optional — falls back to in-memory).
3. Start **TWS or IB Gateway** with API connections enabled
   (Configure → API → Settings → Enable ActiveX and Socket Clients).
   Port 7497 = paper TWS.
4. (Optional) Run `supabase/schema.sql` in your Supabase SQL editor.
5. Run it:
   ```
   python run.py
   ```
   Dashboard: http://127.0.0.1:8000

## Dashboard

- **Kenny chart** — 1-min candles, blue VWAP, yellow dotted prior-day VWAP,
  volume panel, entry/exit markers. Tabs for every watched symbol.
- **Pending signals** — entry/stop/target, confidence breakdown reasons,
  Buy / Ignore buttons. Signals expire after 10 minutes.
- **Open trades** — live marks, unrealized P&L, one-click close.
- **P&L** — today / week / month / lifetime with win rate, avg win/loss,
  profit factor.
- **Rules** — edit auto-trade threshold, trades/day, daily loss, risk per
  trade, position cap at runtime. Big red **Disable Automation** kill switch.

## Tests

```
pytest
```

Covers the VWAP math and the setup detector (faux-show-bro long, VWAP
breakdown short, and the no-fakeout negative case) with synthetic bars.

## Project layout

```
app/
  config.py             env-driven settings
  models.py             Bar, Candidate, Signal, Trade
  data/fmp.py           earnings calendar, surprises, news, quotes
  data/ibkr.py          bars, quotes, bracket orders, positions
  signals/vwap.py       session + anchored VWAP trackers
  signals/detector.py   faux-show-bro & VWAP-breakdown detection
  ai/analyst.py         OpenAI catalyst classification
  ai/confidence.py      45/25/30 technical/fundamental/AI blend
  engine/scanner.py     candidate filtering
  engine/risk.py        daily limits + position sizing
  engine/trader.py      execution + trade lifecycle
  engine/orchestrator.py  the main loop
  api/server.py         FastAPI REST + static dashboard
  web/                  dashboard (lightweight-charts)
supabase/schema.sql     signals/trades/watchlist tables
run.py                  entry point
```
