# Daily Technicals: Research and Scoring

Research date: October 17, 2026. Model version: `daily-v2`.

## What the evidence supports

There is no defensible universal claim that a particular 20/50/200 crossover is
the strongest predictor for individual stocks. The section ranks charts for
human review, not expected returns, win probabilities, or automatic execution.

- [Fidelity: Simple Moving Average](https://www.fidelity.com/learning-center/trading-investing/technical-analysis/technical-indicator-guide/sma)
  describes moving-average slopes, price crosses, and fast/slow crosses as trend
  tools. Longer averages smooth more but lag more. This supports examining the
  cross together with its trend, rather than treating it as a standalone buy/sell rule.
- [Fidelity: Average Volume](https://www.fidelity.com/learning-center/trading-investing/technical-analysis/technical-indicator-guide/average-volume)
  describes above-average volume as evidence of a stronger price move. Our use
  of trigger-day volume versus the *preceding* 20 sessions follows that rationale;
  the exact thresholds are engineering choices, not empirically established cutoffs.
- [Hurst, Ooi and Pedersen: A Century of Evidence on Trend-Following Investing](https://www.aqr.com/-/media/AQR/Documents/Insights/Journal-Article/AQR-JPM-Fall-2017.pdf)
  studies diversified time-series momentum across markets. It supports taking
  trend persistence seriously, but does NOT validate this stock screener, these
  SMA lengths, symmetric long/short profitability, or our scoring weights.

Implementation choice: favor a fresh, still-held price break with volume and
trend agreement over an isolated crossover. Display early reversals too; their
trend component may initially be lower than an established trend's component.

## Signals

The 20/50/200 overlays are **simple moving averages of split-adjusted daily closes**.
Both directions are detected for price/200, 20/50, 20/200 and 50/200 crosses.
A cross requires the previous difference to be zero or opposite in sign and
the current difference to be strictly on the new side. Intraday wicks do not count.

Also detect closes beyond the preceding 20-, 55- and 252-session high/low.
The event bar is excluded from those ranges. A held crossover must stay on its
new side on every subsequent close; a held range break must remain beyond its
original trigger level. Failed events remain visible but cannot qualify a chart.

Only events aged 0-9 sessions qualify. Both bullish and bearish scores are
calculated; the higher side is the displayed ranking direction. Rankings require
220 usable daily bars and the latest bar to be no more than five calendar days
old. The default universe is an editable starter list, NOT an all-market scan
or a claim that the listed securities currently have sufficient liquidity.

## Score: 0-100, Then Penalties

| Component | Maximum | Exact rule |
| --- | ---: | --- |
| Recent held trigger | 30 | Best single trigger: price/200 = 30; 252-day range = 28; 50/200 or 55-day range = 25; AVWAP reclaim/loss = 24; 20/200 = 22; 20/50 or 20-day range = 18. Multiply by `1 - age/10`. Do not add correlated crosses. |
| Trend alignment and slopes | 20 | 4 each for directional price/20, 20/50, 50/200 alignment, and directional 50- and 200-SMA changes over 20 sessions. |
| Trigger-day volume | 20 | `clamp((volume / prior-20-session-average - 1) * 20, 0, 20)`. Full points at 2x. |
| Relative strength vs SPY | 10 | Difference between stock and SPY 63-session price returns, in percentage points in the signal direction; clamped to 0-10. Dates must match. |
| SPY regime agreement | 10 | 5 each for SPY price/200 and 50/200 alignment in the signal direction. |
| Peak anchored VWAP | 10 | 5 if price is on the signal's side of the confirmed swing-high AVWAP, plus 5 if its five-session slope agrees. Unavailable anchors earn zero. |
| Overextension penalty | -15 | 5 points per ATR beyond 2 ATR from SMA20 in the signal direction, capped at 15. ATR14 uses the `ta` library's Wilder implementation. |
| Whipsaw penalty | -10 | Three or more price/200 crosses in the last 20 sessions. |
| Thin turnover penalty | -20 | Last-20-session mean of close times volume below $1 million. No minimum stock price. |
| Earnings proximity penalty | -10 | A returned earnings date falls within the next seven calendar days, including today. |

Clamp the final total to 0-100. Without a held recent trigger, the score is zero.
Unavailable benchmark components earn no points and are disclosed, not imputed.
Unknown earnings produce a warning, not a fictitious "no earnings" clearance.
These are transparent initial heuristics, not fitted or backtested parameters.

## Anchored VWAP Recommendation

For evaluating a recovery after a prior peak, default to a significant swing-high
anchor. A price reclaim indicates trading above the volume-weighted average since
that peak; a rising AVWAP adds trend agreement. This is our interpretation for the
requested review workflow, not a validated prediction of future returns.
[StockCharts' AVWAP explanation](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-overlays/anchored-vwap)
describes significant highs/lows and events as possible anchors, with average-price
support/resistance context. [TradingView's definition](https://www.tradingview.com/support/solutions/43000669764-anchored-vwap-drawing-tool/)
also starts the volume-weighted average at a chosen date.

The indicator does **not** identify current shareholders or their cost bases.
The same shares can trade repeatedly, buyers can exit, and some buyers bought
above the average. Thus, "above AVWAP" does not mean all buyers are no longer
underwater. It is a traded-price proxy for the selected period and feed.

- Default: highest confirmed swing high in the trailing 126 sessions. It must
  exceed all five preceding highs and be at least as high as the five following
  highs. Ties between valid pivots favor the latest. It is only known after the
  fifth later session; no AVWAP crossover event is emitted before or on that
  confirmation date. A loss/reclaim must remain held to qualify.
- Alternate swing low uses the mirrored rule and the lowest confirmed trough.
- Earnings uses the most recent usable calendar event in the last year with known
  timing: before-open anchors that session; after-close anchors the next returned
  trading session. Unknown/during-market times are not guessed. An older usable
  event can be selected if the latest event lacks timing; the exact anchor date
  is always shown and partial calendar coverage is flagged.
  This remains a daily-session approximation, not a timestamp-isolated
  post-announcement VWAP; a daily bar may include trades before the release.
- YTD uses the first returned session in the latest candle's calendar year.
  Custom dates use the first returned session on or after that date; dates
  outside the fetched history are unavailable, not silently substituted.
- Compute `sum(daily_vwap * volume) / sum(volume)` when all positive-volume days
  have valid provider daily VWAP values. Otherwise use HLC3 for the entire anchor
  segment and explicitly label it **Daily HLC3 estimate**. Never mix price methods
  silently, count zero-volume bars as trades, or reset an anchor on display zoom.
- Scores always use the default swing-high anchor for comparability. Changing
  the displayed anchor does not rescore a chart. An anchor can change after a
  new pivot confirms or an old one exits the window. This is current-snapshot
  analysis, not a historical walk-forward signal or trading backtest.

## Price Discovery and Daily Review

A close beyond the prior 252-session intraday high is labeled above the
**52-week high**. A close above every earlier high in the returned data is labeled
above the **fetched-history high**, with at least 252 prior bars required. Neither
is asserted to be an all-time high: the provider fetch covers about six years.
The current candle is excluded from both reference levels. These labels describe
price entering a higher range, not guaranteed follow-through.
[Schwab's breakout guidance](https://www.schwab.com/learn/story/find-breakout-stocks-with-unusual-volume)
also considers volume when examining breakout candidates; it does not validate
our weights or the selection of a particular anchor.

The initial minimum displayed score is 50, adjustable in the scanner. Daily review
takes the highest-ranked 10 or 20 eligible positive-score charts from the current
filters and scan, not stale saved snapshots. Ten charts at roughly 30 seconds each
is a five-minute review; twenty is ten minutes. This is a workflow target, not a
promised completion time or a requirement to fill the queue with weak charts.

Use next/previous buttons or Left/Right arrows. During review, D marks reviewed,
S saves and advances, X passes and advances. Input fields and dialogs keep their
normal keys. Scores, AVWAP state, price-range context, earnings and data warnings
remain visible in the compact review view. The next two charts preload, using a
bounded two-minute browser cache. Review decisions persist by scan session date;
saved picks persist separately and can be revisited with their snapshot dates.
Refresh scans explicitly. No background schedule, order, or trade is created.

## Data and Earnings

- [Alpaca historical bars](https://docs.alpaca.markets/us/reference/stockbars):
  `1Day`, `adjustment=split`, explicit configured IEX or SIP feed, every pagination
  token consumed. Six calendar years are requested so a 5-year display has SMA200
  warmup. Stocks with shorter histories show only available data.
- Conservatively exclude the current New York calendar date, even after the
  closing bell. Rankings are through the prior completed session, displayed as
  "Through YYYY-MM-DD". No current incomplete candle enters a signal.
- Split adjustments avoid split-induced crosses. Cash dividends remain in price
  changes: this is a price-chart model, not total-return performance analysis.
- IEX volume covers one exchange. It is NOT consolidated liquidity and can
  materially change volume scores. Use SIP entitlement for broader coverage;
  there is no silent fallback to a different feed.
- [Finnhub earnings calendar](https://finnhub.io/docs/api/earnings-calendar), also
  documented in its [official client](https://github.com/Finnhub-Stock-API/finnhub-python/blob/master/finnhub/client.py):
  use the event `date` and `hour`, never the fiscal `year`/`quarter` or EPS-history
  period as a report date. Labels distinguish before-open and after-close times.
- Rankings use a cached next-30-day calendar. Chart annotations fetch the selected
  1-5-year period plus 90 days ahead, in bounded windows. Calendar failures are
  marked unavailable/partial. Returned dates may change and historical coverage
  depends on the provider plan; an empty calendar is not proof there are no events.
- Upcoming events occupy whitespace on the time axis, never invented candles.
  Calendar markers are placed on the reported date; an after-close event is not
  shifted onto the following day's price candle.

## Scope and Validation

The new read-only `/api/technicals` router does not call order-placement services
or alter the morning VWAP strategy. Server caches are bounded, bars refresh after
15 minutes, and successful earnings responses after one hour. Each scan accepts
at most 100 symbols; the browser persists the chosen list, ticker, and range.

Before using rankings as a trading model, test point-in-time constituents including
delistings, publication-time earnings calendars, out-of-sample periods, spreads,
fees, dividends, short availability and borrow costs. Test bullish and bearish
results separately. Current constituents, subsequently adjusted data and today's
earnings calendar cannot produce an unbiased historical trading simulation.

## Verification

Run `python -m pytest -q` and
`node --test tests/test_dashboard.cjs tests/test_technicals.cjs`.
The optional `node tests/browser_technicals.cjs` requires Playwright and a running
offline preview at `http://127.0.0.1:8012` (override with `PREVIEW_URL`). Set
`BROWSER_CHANNEL=msedge` to use installed Edge instead of a Playwright browser.
It checks the real unconfigured state before intercepting market-data routes with
explicit synthetic fixtures. It exercises chart pixels, future earnings placement,
filters, fast selection races, 5-year visible history after mobile resizing,
AVWAP anchors, review shortcuts/progress, saved picks, errors and persisted preferences;
screenshots go to the system temp
directory or `SCREENSHOT_DIR`. This is not a live-provider acceptance test.
