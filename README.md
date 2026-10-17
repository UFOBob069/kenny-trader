# VWAP Event Trading Copilot

## Paper Results and Daily Plans

Paper Setup Results now uses broker-confirmed closed fills, grouped by setup,
direction and strategy version. Unfilled orders and legacy estimated P&L are
excluded. Daily Technicals adds research-only entry, stop-loss and 2R levels,
including explicit wait/unavailable states. These plans do not submit orders.

Trade history restores from Supabase's existing settings JSONB journal or local
SQLite (`STATE_DB_PATH=data/paper.sqlite3`). Railway needs Supabase or a mounted
volume with STATE_DB_PATH under RAILWAY_VOLUME_MOUNT_PATH; otherwise new paper
entries are blocked. Run one worker/replica. See the authoritative
[tracking/plan contract](product/PAPER_TRACKING_AND_DAILY_PLANS.md) for accounting,
storage, execution risks and remaining limits; older descriptions below may predate it.

## Current Authority: Paper Only

Live execution is disabled in this release. Alpaca's paper endpoint is selected
unconditionally and verified before every broker mutation. `ALPACA_PAPER=false`
cannot select live trading. IBKR connects read-only and rejects order mutations.

`EXECUTION_MODE=paper` permits automated paper experiments; automation defaults ON
with the existing score, freshness, liquidity and risk checks. Set
`EXECUTION_MODE=research` to block manual orders, automation and exit attachment
at the API, engine and broker layers. Live is not a valid mode and cannot be
enabled from dashboard settings. Use paper API credentials.

`AUTO_TRADE_ENABLED=false` disables automatic paper entries at startup. The runtime
toggle resets to the environment/default on restart. A mode change never cancels
existing broker orders or liquidates positions. Manage those in the broker.

Paper trading does not establish profitability. App P&L is labeled **unverified**
while fill reconciliation and restart recovery remain open work. Pending entries
reserve a daily trade slot immediately and are not counted again when filled;
canceled orders conservatively retain their slot until the daily reset.

The Russell filter still uses the IWB proxy, now from the
[issuer's holdings download](https://www.ishares.com/us/products/239707/ishares-russell-1000-etf).
It validates the publication date (maximum five calendar days), equity count and
aggregate weight; caches success for the day; and retries failures after five
minutes. Missing/stale/incomplete data pauses the filter without widening it.
These integrity checks do not guarantee exact official index membership.

Independent cap, watchlist and candidate lookups run with concurrency capped at
four. Up to `MAX_ACTIVE_SYMBOLS=100` filtered symbols receive chart/RVOL history
instead of twelve; unmonitored symbols and source diagnostics are disclosed in
status. Qualification thresholds have not been loosened. Coverage recovery is
not yet evidence of better trading outcomes.

See [first roadmap delivery](product/DELIVERY_2026-10-17.md). The historical overview
below is superseded by this authority policy and Current Engine Behavior.

## Current Engine Behavior

Qualification uses observed liquidity instead of a minimum stock price;
legacy `MIN_PRICE` values are ignored. Initial configurable limits require
at least $250,000 estimated turnover in the last five completed minutes,
trading in four of those five minutes, and a bid/ask spread no wider than 1%
from a quote at most 15 seconds old. Turnover uses each minute's close times
volume and is therefore an estimate. No missing-data fallback qualifies a stock.

Before either manual or automatic entry, the engine fetches a fresh bid/ask
quote, uses the executable side for the missed-entry check, and rechecks activity.
The planned share quantity must be no more than 1% of the trailing five-minute
average shares per minute. The spread must also be at most 20% of the setup's
stop distance. These defaults need paper-session calibration for the chosen feed
and order sizes; they are not asserted to be Kenny's rules. Level 1 quotes and
recent volume do not establish full order-book depth or guarantee a fill.

The scanner now refreshes every 60 seconds and polls completed minute candles
every 10 seconds, using a batch request for Alpaca (up to four concurrent symbol
requests for IBKR). These are polling
intervals, not guarantees of data delivery latency. The status API includes scan
duration, poll duration, configured feed, and the latest bar timestamp per symbol.

Only qualified candidates can publish setups. Rolling history is consumed by
timestamp, old catch-up signals are suppressed, and VWAP resets on the Eastern
calendar day. The yellow line anchors to exactly the latest available prior
session. Long targets must have room to the nearer of the session high or an
overhead prior-day VWAP; shorts must have room
to the prior-session anchored VWAP. There is no synthetic 2R target fallback.

Catalyst analysis is prepared in the background. Setup ranking is technical;
earnings and AI no longer boost or penalize a reversal's score. An uncached
analysis uses a neutral context placeholder. Signals older than
90 seconds from their trigger candle's close, or with stale chart data, are
rejected; approval also rechecks the latest available quote. Poll and freshness
limits are configurable in `.env.example`.

Relative volume compares accumulated completed-bar volume with the same Eastern
minute in up to five preceding sessions (at least three required). Profiles are
built from the history already fetched for active charts, so uninitialized
symbols cannot qualify on unknown volume. No extra history request is needed.
Sparse IEX history may leave some symbols unqualified.

Enabled universe filters require verified data. If Russell membership or the
exchange asset list cannot load, the scan pauses instead of silently widening.
An unknown market cap is excluded when a cap floor is enabled and retried on
the next scan. `/api/status` reports these conditions in `scan_filter_errors`.

By default, new entries are limited to 08:30-09:15 and 09:35-11:30 Eastern.
`MORNING_ONLY=false` permits the rest of the extended session. This setting does
not liquidate open positions. These conservative windows follow the discussion
at [38:00 in the reference video](https://www.youtube.com/watch?v=qtUFsbNOgSk&t=2280s).
Local range lows use five preceding candles, and a shakeout must reclaim VWAP
within ten candles. The [PayPal example at 13:30](https://www.youtube.com/watch?v=qtUFsbNOgSk&t=810s)
motivates using a recent range rather than requiring a new full-day low.

Remaining validation: the numerical lookback, gap (current change from previous
close), RVOL and freshness thresholds are engineering choices, not parameters
specified by Kenny. His proprietary chart script is not reproduced exactly.
The score is not a calibrated win probability. Recorded morning sessions are
needed to validate signal quality and feed coverage against reference charts.

The original overview below describes the project architecture; where its
timing or freshness descriptions differ, the current behavior above applies.

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
node --test tests/test_dashboard.cjs
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

## Daily Technicals

Open `/technicals` (also linked from the morning dashboard) for a separate,
read-only daily chart screener. It includes 1-5 year daily candlesticks, SMA
20/50/200 overlays, bullish and bearish crosses, price/200 and range breaks,
earnings markers, an editable scan universe, and explainable 0-100 rankings.
Anchored VWAP defaults to a confirmed six-month swing high, with swing-low,
earnings-reaction, YTD and custom-date alternatives. Reclaim/loss signals and
52-week range breaks join the rankings. The Daily review action builds a top-10
or top-20 queue with preloaded next charts, saved picks and review progress.
The score is a review heuristic, not a win probability. This section cannot
submit trades and does not change the morning VWAP engine.

Uses the existing `ALPACA_API_KEY`, `ALPACA_SECRET_KEY`, `ALPACA_DATA_FEED`, and
`FINNHUB_API_KEY` settings. IEX is not consolidated volume. Missing credentials,
limited earnings coverage and provider errors are shown explicitly. Current-day
bars are excluded; the chart displays its last included session date.

Research sources, exact scoring weights, limitations and data behavior:
[Daily Technicals methodology](docs/DAILY_TECHNICALS.md).
