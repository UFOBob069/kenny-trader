"""Daily anchored averages and explicitly bounded price-discovery context."""
from __future__ import annotations

import pandas as pd


def select_anchor(data: pd.DataFrame, mode: str, anchor_date: str | None = None,
                  earnings: list[dict] | None = None) -> dict:
    if data.empty:
        return {'available': False, 'reason': 'No daily history.'}
    index = None
    confirmed = None
    label = mode
    if mode in ('swing_high', 'swing_low'):
        high = mode == 'swing_high'
        series = data.high if high else data.low
        candidates = []
        # Five sessions on either side. Confirmation is not known on the pivot day.
        for i in range(max(5, len(data) - 126), len(data) - 5):
            left, right = series.iloc[i - 5:i], series.iloc[i + 1:i + 6]
            pivot = (series.iloc[i] > left.max() and series.iloc[i] >= right.max()) if high else (
                series.iloc[i] < left.min() and series.iloc[i] <= right.min())
            if pivot:
                candidates.append(i)
        if candidates:
            index = max(candidates, key=lambda i: (series.iloc[i] if high else -series.iloc[i], i))
            confirmed = index + 5
        label = '6-month swing high' if high else '6-month swing low'
    elif mode == 'ytd':
        start = data.time.iloc[-1][:4] + '-01-01'
        indices = data.index[data.time >= start]
        index = int(indices[0]) if len(indices) else None
        confirmed = index
        label = 'Year to date'
    elif mode == 'custom':
        if anchor_date and data.time.iloc[0] <= anchor_date <= data.time.iloc[-1]:
            indices = data.index[data.time >= anchor_date]
            index = int(indices[0]) if len(indices) else None
        confirmed = index
        label = 'Custom date'
    elif mode == 'earnings':
        # Daily candles cannot isolate a during-market announcement. Do not guess its time.
        for event in sorted(earnings or [], key=lambda e: e['date'], reverse=True):
            if event.get('hour') not in ('bmo', 'amc') or event['date'] > data.time.iloc[-1]:
                continue
            indices = data.index[data.time > event['date']] if event['hour'] == 'amc' else data.index[data.time >= event['date']]
            if len(indices):
                index = int(indices[0])
                confirmed = index
                break
        label = 'Earnings reaction session'
    else:
        raise ValueError('Unknown AVWAP anchor.')
    if index is None:
        reason = {'swing_high': 'No confirmed swing high in the last 126 sessions.',
                  'swing_low': 'No confirmed swing low in the last 126 sessions.',
                  'custom': 'Anchor date must fall inside the available completed history.',
                  'ytd': 'No completed sessions in the anchor year.',
                  'earnings': 'No usable earnings date with a known before-open or after-close time.'}[mode]
        return dict(available=False, mode=mode, label=label,
                    reason=reason)
    return dict(available=True, mode=mode, label=label, index=index,
                date=data.time.iloc[index], confirmed_index=confirmed, confirmed_at=data.time.iloc[confirmed])


def anchored_vwap(data: pd.DataFrame, mode='swing_high', anchor_date=None, earnings=None) -> dict:
    anchor = select_anchor(data, mode, anchor_date, earnings)
    if not anchor['available']:
        return dict(anchor=anchor, series=pd.Series(float('nan'), index=data.index), events=[],
                    value=None, distance_pct=None, slope='unknown', method='unavailable', state='Unavailable')
    start = anchor['index']
    segment = data.iloc[start:]
    valid_volume = segment.volume.where(segment.volume > 0, 0)
    use_provider = 'vwap' in segment and segment.loc[valid_volume > 0, 'vwap'].notna().all()
    source = segment.vwap if use_provider else (segment.high + segment.low + segment.close) / 3
    values = (source.fillna(0) * valid_volume).cumsum() / valid_volume.cumsum().replace(0, float('nan'))
    series = values.reindex(data.index)
    result_events = []
    for sign, side in ((1, 'bullish'), (-1, 'bearish')):
        difference = (data.close - series) * sign
        crossed = (difference > 0) & (difference.shift(1) <= 0) & (data.volume > 0)
        for i in data.index[crossed]:
            if i <= anchor['confirmed_index']:
                continue
            result_events.append(dict(kind='avwap', label='AVWAP reclaim' if sign == 1 else 'AVWAP loss',
                                      direction=side, time=data.time.iloc[i], index=int(i),
                                      level=round(float(series.iloc[i]), 4), weight=24,
                                      held=bool((difference.iloc[i:] > 0).all()), anchor_date=anchor['date']))
    last = series.iloc[-1]
    value = round(float(last), 4) if pd.notna(last) else None
    slope = 'unknown'
    if len(values) >= 6 and pd.notna(values.iloc[-6]) and pd.notna(last):
        slope = 'rising' if last > values.iloc[-6] else 'falling' if last < values.iloc[-6] else 'flat'
    return dict(anchor=anchor, series=series, events=result_events, value=value,
                distance_pct=round((float(data.close.iloc[-1]) / last - 1) * 100, 2) if value else None,
                slope=slope, method='Provider daily VWAP x volume' if use_provider else 'Daily HLC3 estimate',
                state='Above anchored average' if value and data.close.iloc[-1] > last else
                'Below anchored average' if value and data.close.iloc[-1] < last else 'At anchored average' if value else 'Unavailable')


def public_avwap(result: dict) -> dict:
    return {key: value for key, value in result.items() if key not in ('series', 'events')}


def discovery_context(data: pd.DataFrame) -> dict:
    if len(data) < 2:
        return {'state': 'Insufficient history', 'high_52w': None, 'history_high': None}
    previous = data.iloc[:-1]
    high = float(previous.high.max())
    annual = float(previous.high.iloc[-252:].max()) if len(previous) >= 252 else None
    close = float(data.close.iloc[-1])
    at_history = len(previous) >= 252 and close > high
    at_52 = annual is not None and close > annual
    return dict(state='Above fetched-history high' if at_history else 'Above 52-week high' if at_52 else 'Inside prior range',
                high_52w=round(annual, 4) if annual is not None else None,
                history_high=round(high, 4), history_start=data.time.iloc[0],
                above_52w=at_52, above_history=at_history,
                distance_to_52w_pct=round((close / annual - 1) * 100, 2) if annual else None)
