"""Daily-bar chart research, including provisional sessions. Heuristic scores."""
from __future__ import annotations

from datetime import date
import math

import pandas as pd
from ta.trend import SMAIndicator
from ta.volatility import AverageTrueRange
from app.engine.anchored_vwap import anchored_vwap, discovery_context, public_avwap


def frame(bars: list[dict]) -> pd.DataFrame:
    data = pd.DataFrame(bars)
    if data.empty:
        return data
    data = data.drop_duplicates('time', keep='last').sort_values('time').reset_index(drop=True)
    for window in (20, 50, 200):
        data[f'sma{window}'] = SMAIndicator(data.close, window).sma_indicator()
    if len(data) >= 14:
        data['atr'] = AverageTrueRange(data.high, data.low, data.close, 14).average_true_range()
    else:
        data['atr'] = float('nan')
    data['volume_ratio'] = data.volume / data.volume.shift(1).rolling(20).mean().replace(0, float('nan'))
    return data


def number(value):
    return round(float(value), 4) if pd.notna(value) and math.isfinite(float(value)) else None


def events(data: pd.DataFrame) -> list[dict]:
    """Crossing comparisons use each day's own average; ranges exclude the event bar."""
    result = []
    comparisons = [('price200', 'Price / SMA 200', data.close, data.sma200, 30),
                   ('ma20_50', 'SMA 20 / 50', data.sma20, data.sma50, 18),
                   ('ma20_200', 'SMA 20 / 200', data.sma20, data.sma200, 22),
                   ('ma50_200', 'SMA 50 / 200', data.sma50, data.sma200, 25)]
    for code, label, fast, slow, weight in comparisons:
        for sign, side in ((1, 'bullish'), (-1, 'bearish')):
            difference = (fast - slow) * sign
            crossed = (difference > 0) & (difference.shift(1) <= 0)
            for i in data.index[crossed]:
                result.append(dict(kind=code, label=label, direction=side, time=data.time[i],
                                   index=int(i), level=number(slow[i]), weight=weight,
                                   held=bool((difference.iloc[i:] > 0).all())))
    for window, weight in ((20, 18), (55, 25), (252, 28)):
        for sign, side, extremes in ((1, 'bullish', data.high), (-1, 'bearish', data.low)):
            level = extremes.shift(1).rolling(window).max() if sign == 1 else extremes.shift(1).rolling(window).min()
            crossed = (data.close * sign > level * sign) & (data.close.shift(1) * sign <= level.shift(1) * sign)
            for i in data.index[crossed]:
                result.append(dict(kind=f'range{window}', label=f'{window}-day range' if window != 252 else '52-week range', direction=side,
                                   time=data.time[i], index=int(i), level=number(level[i]), weight=weight,
                                   held=bool(((data.close.iloc[i:] - level[i]) * sign > 0).all())))
    return sorted(result, key=lambda item: (item['time'], item['kind']))


def analyze(symbol: str, bars: list[dict], benchmark: list[dict], today: date,
            earnings: list[dict] | None = None) -> dict:
    data = frame(bars)
    base = dict(symbol=symbol, as_of=bars[-1]['time'] if bars else None,
                eligible=False, score=0, direction='neutral', signals=[], breakdown=[], warnings=[],
                chart_assessment=dict(version='chart-v1', available=False, score=None,
                    reason=f'Chart score needs 220 usable daily bars; {len(data)} available.'))
    if len(data) < 220:
        return {**base, 'warnings': ['At least 220 usable daily bars are required.'],
                'history_bars': len(data), 'close': number(data.close.iloc[-1]) if len(data) else None}
    last = data.iloc[-1]
    avwap = anchored_vwap(data)
    discovery = discovery_context(data)
    all_events = sorted(events(data) + avwap['events'], key=lambda e: (e['time'], e['kind']))
    recent = [{**e, 'age': len(data) - 1 - e['index']} for e in all_events
              if len(data) - 1 - e['index'] < 10]
    active = [e for e in recent if e['held']]
    stale = (today - date.fromisoformat(last.time)).days > 5
    # Align benchmark to the same dates. No forward filling or future benchmark information.
    bench = frame(benchmark)
    relative = None
    market = None
    if not bench.empty:
        bench = bench[bench.time <= last.time]
        joined = data[['time', 'close']].merge(bench[['time', 'close']], on='time', suffixes=('', '_spy'))
        if len(joined) >= 64 and joined.time.iloc[-1] == last.time:
            relative = (joined.close.iloc[-1] / joined.close.iloc[-64] -
                        joined.close_spy.iloc[-1] / joined.close_spy.iloc[-64]) * 100
        if len(bench) >= 220 and bench.time.iloc[-1] == last.time:
            market = bench.iloc[-1]
    dollar_volume = float((data.close * data.volume).iloc[-20:].mean())
    warnings = []
    if stale:
        warnings.append('Stale daily history; excluded from ranked signals.')
    if relative is None or market is None:
        warnings.append('SPY comparison unavailable; missing components earn no points.')
    upcoming = sorted([e for e in (earnings or []) if e['date'] >= today.isoformat()], key=lambda e: e['date'])
    next_earnings = upcoming[0] if upcoming else None
    if earnings is None:
        warnings.append('Earnings calendar unavailable; event risk is unknown.')
    elif not next_earnings:
        warnings.append('No upcoming earnings date returned; event risk is not cleared.')
    if dollar_volume < 1_000_000:
        warnings.append('Low 20-day average dollar turnover on the selected feed.')
    if not avwap['anchor']['available']:
        warnings.append('No confirmed swing-high AVWAP anchor; its score component earns no points.')
    crosses = [e for e in all_events if e['kind'] == 'price200' and len(data) - 1 - e['index'] < 20]
    scores = []
    assessments = []
    for sign, side in ((1, 'bullish'), (-1, 'bearish')):
        candidates = [e for e in active if e['direction'] == side]
        trigger = max(candidates, key=lambda e: e['weight'] * (1 - e['age'] / 10), default=None)
        trigger_points = trigger['weight'] * (1 - trigger['age'] / 10) if trigger else 0
        alignment = sum(sign * (a - b) > 0 for a, b in
                        [(last.close, last.sma20), (last.sma20, last.sma50), (last.sma50, last.sma200)]) * 5
        slope = sum(sign * (last[f'sma{w}'] - data[f'sma{w}'].iloc[-21]) > 0 for w in (50, 200)) * 5
        vol = data.iloc[trigger['index']].volume_ratio if trigger else float('nan')
        volume_points = max(0, min(20, (float(vol) - 1) * 20)) if pd.notna(vol) else 0
        relative_points = max(0, min(10, sign * relative)) if relative is not None else 0
        avwap_points = 0
        if avwap['value'] and sign * (last.close - avwap['value']) > 0:
            avwap_points = 5
            if avwap['slope'] == ('rising' if sign == 1 else 'falling'):
                avwap_points += 5
        market_points = 0
        if market is not None:
            market_points = 5 * int(sign * (market.close - market.sma200) > 0)
            market_points += 5 * int(sign * (market.sma50 - market.sma200) > 0)
        extension = max(0, sign * (last.close - last.sma20) / last.atr) if last.atr > 0 else 0
        penalty_extension = min(15, max(0, extension - 2) * 5)
        penalty_chop = 10 if len(crosses) >= 3 else 0
        penalty_liquidity = 20 if dollar_volume < 1_000_000 else 0
        days_to_earnings = (date.fromisoformat(next_earnings['date']) - today).days if next_earnings else None
        penalty_earnings = 10 if days_to_earnings is not None and days_to_earnings <= 7 else 0
        components = [
            ('Recent held trigger', trigger_points, 30, trigger['label'] if trigger else 'No held trigger in 10 sessions'),
            ('Trend alignment + slope', (alignment + slope) * .8, 20, 'Price / 20 / 50 / 200 and 20-session slopes'),
            ('Trigger-day volume', volume_points, 20, f'{number(vol)}x prior 20 sessions' if pd.notna(vol) else 'Unavailable'),
            ('63-session strength vs SPY', relative_points, 10, f'{number(relative)} percentage points' if relative is not None else 'Unavailable'),
            ('SPY trend agreement', market_points, 10, 'Price / 200 and 50 / 200'),
            ('Peak anchored VWAP', avwap_points, 10, f"{avwap['state']}; {avwap['slope']}"),
            ('Overextension', -penalty_extension, 0, f'{extension:.1f} ATR from SMA 20'),
            ('200-day whipsaws', -penalty_chop, 0, f'{len(crosses)} price crosses in 20 sessions'),
            ('Thin dollar turnover', -penalty_liquidity, 0, f'${dollar_volume:,.0f} average / day'),
            ('Earnings within 7 days', -penalty_earnings, 0, next_earnings['date'] if next_earnings else 'Unknown'),
        ]
        points = round(max(0, min(100, sum(c[1] for c in components))), 1)
        breakdown = [dict(label=l, points=round(float(p), 1), maximum=m, detail=d) for l, p, m, d in components]
        assessments.append(dict(direction=side, score=points, breakdown=breakdown))
        scores.append(dict(direction=side, score=points if trigger else 0, trigger=trigger, breakdown=breakdown))
    chosen = max(scores, key=lambda s: (s['score'], s['trigger']['time'] if s['trigger'] else ''))
    chart_assessment = dict(version='chart-v1', available=True, **max(assessments, key=lambda s: s['score']),
                            bullish_score=assessments[0]['score'], bearish_score=assessments[1]['score'])
    return {**base, **chosen, 'eligible': bool(chosen['trigger']) and not stale,
            'chart_assessment': chart_assessment,
            'as_of': last.time, 'close': number(last.close),
            'change_pct': number((last.close / data.close.iloc[-2] - 1) * 100),
            'sma': {str(w): number(last[f'sma{w}']) for w in (20, 50, 200)},
            'atr': number(last.atr), 'dollar_volume': round(dollar_volume),
            'relative_strength': number(relative), 'volume_ratio': number(last.volume_ratio),
            'signals': recent, 'warnings': warnings, 'next_earnings': next_earnings,
            'avwap': public_avwap(avwap), 'discovery': discovery,
            'bullish_score': scores[0]['score'], 'bearish_score': scores[1]['score'],
            'history_bars': len(data)}


def chart_payload(bars: list[dict], years: int, today: date, anchor='swing_high', anchor_date=None, earnings=None) -> dict:
    data = frame(bars)
    if data.empty:
        return {'bars': [], 'averages': {}, 'events': []}
    start = today.replace(year=today.year - years, day=min(today.day, 28)) if today.month == 2 else today.replace(year=today.year - years)
    visible = data[data.time >= start.isoformat()]
    vwap = anchored_vwap(data, anchor, anchor_date, earnings)
    return {
        'bars': visible[['time', 'open', 'high', 'low', 'close', 'volume']].to_dict('records'),
        'averages': {str(w): [{'time': r.time, 'value': number(getattr(r, f'sma{w}'))}
                            for r in visible.itertuples() if pd.notna(getattr(r, f'sma{w}'))] for w in (20, 50, 200)},
        'events': sorted([e for e in events(data) + vwap['events'] if e['time'] >= start.isoformat()], key=lambda e: (e['time'], e['kind'])),
        'avwap': {**public_avwap(vwap), 'points': [dict(time=data.time.iloc[i], value=number(value))
                  for i, value in vwap['series'].items() if pd.notna(value) and data.time.iloc[i] >= start.isoformat()]},
    }
