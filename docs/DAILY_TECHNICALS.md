# Daily Technicals: Research and Scoring

Research date: October 17, 2026. Updated October 19, 2026.
Model version: `daily-v4-volatility`; chart assessment: `chart-v2-volatility`.
The added volatility evidence reallocates 15 points within the existing 100-point
scale. Scores from earlier model versions are not directly comparable.

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
the current difference to be strictly on the new side. Intraday wicks alone do not
count. Today's snapshot close is provisional, not a finalized closing price, so
today's crosses can appear or disappear before the session ends.

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
| Recent held trigger | 25 | Best single trigger base weight: price/200 = 30; 252-day range = 28; 50/200 or 55-day range = 25; AVWAP reclaim/loss = 24; 20/200 = 22; 20/50 or 20-day range = 18. Multiply by `(1 - age/10) * 25/30`. Do not add correlated crosses. |
| Trend alignment and slopes | 15 | 3 each for directional price/20, 20/50, 50/200 alignment, and directional 50- and 200-SMA changes over 20 sessions. |
| Trigger-day volume | 15 | `clamp((volume / prior-20-session-average - 1) * 15, 0, 15)`. Full points at 2x. |
| Relative strength vs SPY | 10 | Difference between stock and SPY 63-session price returns, in percentage points in the signal direction; clamped to 0-10. Dates must match. |
| SPY regime agreement | 10 | 5 each for SPY price/200 and 50/200 alignment in the signal direction. |
| Peak anchored VWAP | 10 | 5 if price is on the signal's side of the confirmed swing-high AVWAP, plus 5 if its five-session slope agrees. Unavailable anchors earn zero. |
| Volatility compression | 5 | 3 when BB width is at/below the preceding 126-bar 20th percentile AND ATR14 is below its value five sessions ago; 2 when squeeze is on. Same points on both sides: neutral watch evidence, never an entry trigger. |
| Donchian breakout confirmation | 5 | Current close beyond the prior 20-bar high/low in this direction, with compression on at least one of the preceding five bars. Compression means squeeze on OR narrow BB width plus declining ATR. |
| Squeeze release confirmation | 5 | Release in the current/prior four bars, squeeze currently off, momentum on this side of zero and strengthening versus the previous bar, and close on this side of SMA20. |
| Overextension penalty | -15 | 5 points per ATR beyond 2 ATR from SMA20 in the signal direction, capped at 15. ATR14 uses the `ta` library's Wilder implementation. |
| Whipsaw penalty | -10 | Three or more price/200 crosses in the last 20 sessions. |
| Thin turnover penalty | -20 | Last-20-session mean of close times volume below $1 million. No minimum stock price. |
| Earnings proximity penalty | -10 | A returned earnings date falls within the next seven calendar days, including today. |

Clamp the final total to 0-100. Without a held recent trigger, the score is zero.
Unavailable benchmark components earn no points and are disclosed, not imputed.
Unknown earnings produce a warning, not a fictitious "no earnings" clearance.
These are transparent initial heuristics, not fitted or backtested parameters.

### Any-Ticker Chart Assessment

`chart-v2-volatility` evaluates every supported ticker opened in the chart, independent of
scan-universe membership. The displayed **Chart score** is the stronger of the
bullish and bearish evidence totals using the same weights and penalties above,
but without the final no-trigger-to-zero override. Both directional totals are
shown; the breakdown belongs to the displayed direction (bullish on an exact tie).
Without a fresh trigger, trigger and trigger-day volume earn zero, so the maximum
chart score cannot exceed 60 before penalties. Missing components are not rescaled or imputed.

The scanner's **setup score** uses the revised weights too; qualification rules
and research trade-plan gates remain unchanged. A chart assessment is not permission to trade, a probability,
or evidence of profitability. A strong ongoing trend may have a nonzero chart
score but no qualifying recent breakout and therefore no trade plan. At least
220 usable daily bars are required; otherwise the chart score is unavailable
with the available bar count, not zero. Intraday scores remain provisional and
stale/as-of/feed warnings apply to this assessment too.

## Volatility Studies

- **Bollinger Bands (20, 2):** SMA20 of closes plus/minus twice population standard
  deviation (`ddof=0`). Width is `(upper-lower)/middle * 100`. The narrow flag uses
  only the preceding 126 valid widths, not future observations or a universal
  fixed threshold. [Fidelity's Bollinger description](https://www.fidelity.com/learning-center/trading-investing/technical-analysis/technical-indicator-guide/bollinger-bands)
  supports the band/volatility interpretation, not our score cutoffs.
- **TTM-style Squeeze:** BB fully inside Keltner means on; the first valid off bar
  after on means released. Red dots show on, green off, amber the release bar.
  We explicitly use the modern **EMA20 of close +/- 1.5 x Wilder ATR20** Keltner
  variant supplied by `ta`. It can differ from StockCharts' original-Keltner TTM
  implementation; this is not a promise of vendor-identical signals. Momentum is
  the last fitted value of a rolling 20-bar least-squares regression on
  `close - (current 20-bar Donchian midpoint + SMA20)/2`, following the public
  [StockCharts momentum construction](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-indicators/ttm-squeeze).
  Positive/negative and strengthening/weakening momentum use four histogram colors.
- **Donchian (20):** highest high, lowest low and midpoint of the **preceding** 20
  bars. The display is shifted one bar so today's candle cannot move its own
  breakout threshold. This is an explicit offset from the usual rolling channel
  described by [TradingView](https://www.tradingview.com/support/solutions/43000502253-donchian-channels-dc/).
- **ATR (14):** Wilder-smoothed true range, including gaps relative to the previous
  close; also display percentage change versus five sessions ago. It measures
  movement, not direction. [Fidelity's ATR guide](https://www.fidelity.com/learning-center/trading-investing/technical-analysis/technical-indicator-guide/atr).

Indicators use the full history before slicing the selected 1-5-year view. Warmup
bars are unavailable, not invented zeroes: BB/Keltner/squeeze need 20 bars,
prior Donchian 21, ATR 14, regression momentum 39. The 126-bar width reference
needs 146 total bars. Current-day values and scores remain provisional. Visual
toggles do not change scores. Pan/zoom and crosshairs are synchronized between
price, squeeze and ATR, including future earnings whitespace.

Compression evidence overlaps other technical indicators; do not interpret the
15-point allocation as independent statistical evidence. It is a bounded initial
heuristic, not fitted or validated performance. Neither compression nor release
alone bypasses the existing fresh held-signal, score, freshness or trade-plan gates.

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
bounded 30-second browser cache. Review decisions persist by scan session date;
saved picks persist separately and can be revisited with their snapshot dates.
The visible page refreshes rankings and the selected chart every 60 seconds and
on returning to the tab. Manual refresh also updates the selected chart. Zoom,
selection and the active review queue/decisions are preserved. This is page
polling, not a scheduled task or trade automation. No order is created.

## Data and Earnings

- [Alpaca historical bars](https://docs.alpaca.markets/us/reference/stockbars):
  `1Day`, `adjustment=split`, explicit configured IEX or SIP feed, every pagination
  token consumed. Six calendar years are requested so a 5-year display has SMA200
  warmup. Stocks with shorter histories show only available data.
- Keep prior history cached for 15 minutes and merge today's
  [Alpaca snapshot dailyBar](https://docs.alpaca.markets/us/reference/stocksnapshots-1)
  from the same configured feed, cached for 30 seconds. Only a valid bar dated
  today in New York is appended. Never synthesize a candle from a latest trade,
  reuse a previous-session snapshot as today, or append a future-dated bar.
  Charts, SMA/AVWAP, rankings and research plans use the same merged bars.
- Label today's candle, score and plan provisional, including after close until
  the historical path supplies it the following date. Current-day volume is
  partial, compared with full prior sessions, not extrapolated/time-normalized.
  Snapshot check time and latest feed-trade timestamp are distinct; the latter
  is available on the as-of label's tooltip. Polling is not streaming tick data.
- Missing snapshots show explicit prior-history/unavailable status. During
  regular/post-market hours, no current bar means no ranked signal or trade plan;
  provider failures exclude rankings even outside those hours. Pre-open without
  a current bar may display prior-session rankings but no plan. Closed periods
  can show prior-session context. Weekday/time checks are not an exchange holiday
  calendar; holiday/early-close expected-session handling remains KT-006 work.
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
