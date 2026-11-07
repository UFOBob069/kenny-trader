"""A conservative single-degree Elliott interpretation; not a predictive model."""
import numpy as np
from numpy.lib.stride_tricks import sliding_window_view


def swing_pivots(data):
    if len(data) < 7:
        return []
    dates = data.time.to_numpy()
    atr = data.atr.to_numpy()
    candidates = []
    for kind, values in [('high', data.high.to_numpy()), ('low', data.low.to_numpy())]:
        windows = sliding_window_view(values, 7)
        extreme = windows.max(axis=1) if kind == 'high' else windows.min(axis=1)
        unique = (windows == extreme[:, None]).sum(axis=1) == 1
        for index in np.flatnonzero(unique & (windows[:, 3] == extreme)) + 3:
            candidates.append((int(index), kind, float(values[index])))
    swings = []
    counts = {}
    for i, _, _ in candidates:
        counts[i] = counts.get(i, 0) + 1
    for i, kind, price in sorted(candidates):
        if counts[i] != 1:  # Outside bars have ambiguous intraday ordering.
            continue
        pivot = dict(i=i, kind=kind, price=price, time=dates[i], confirmed_on=dates[i+3])
        if swings:
            prev = swings[-1]
            sign = 1 if kind == 'high' else -1
            move = sign * (price - prev['price'])
            if prev['kind'] == kind:
                if move > 0:
                    swings[-1] = pivot
                continue
            if move < max(prev['price'] * .03, 1.5 * atr[i] if np.isfinite(atr[i]) else 0):
                continue
        swings.append(pivot)
    return swings


def classify(pivots):
    # Only count a suffix ending at the last confirmed pivot. Prefer a complete
    # impulse plus simple correction over relabeling its last legs as a new count.
    for length in range(min(9, len(pivots)), 3, -1):
        p = pivots[-length:]
        sign = 1 if p[0]['kind'] == 'low' else -1
        v = [sign * point['price'] for point in p]
        if not v[0] < v[2] < v[1] < v[3]:
            continue
        if length >= 5 and not v[1] < v[4] < v[3]:
            continue
        if length >= 6 and (v[5] <= v[3] or v[3]-v[2] < min(v[1]-v[0], v[5]-v[4])):
            continue
        if length >= 7 and not v[0] < v[6] < v[5]:
            continue
        if length >= 8 and not v[6] < v[7] < v[5]:
            continue
        if length == 9 and not v[8] < v[6]:
            continue
        labels = '012345ABC'
        return dict(direction='bullish' if sign == 1 else 'bearish',
                    retracement2_pct=round(100 * (v[1]-v[2]) / (v[1]-v[0]), 1),
                    extension3=round((v[3]-v[2]) / (v[1]-v[0]), 2),
                    phase=('Impulse through ' + labels[length-1] if length <= 6 else 'Correction through ' + labels[length-1]),
                    pivots=[{**point, 'label': label} for point,label in zip(p, labels)])
    return None


def wave_context(data, today):
    closed = data[data.time < today.isoformat()].tail(260)
    result = dict(available=False, reason='No qualifying recent wave count.', pivots=[],
                  as_of=closed.time.iloc[-1] if len(closed) else None)
    if len(closed) < 30:
        return {**result, 'reason': 'Insufficient completed sessions (need 30).'}
    count = classify(swing_pivots(closed))
    if not count:
        return result
    last = count['pivots'][-1]
    if len(closed)-1-last['i'] > 20:
        return result
    # A developing fourth leg overlapping wave one invalidates a standard count
    # even before that leg is confirmed as a swing.
    if last['label'] in ('3', '4'):
        boundary = count['pivots'][1]['price']
        tail = closed.iloc[last['i']+1:]
        if (count['direction'] == 'bullish' and tail.low.min() <= boundary or
                count['direction'] == 'bearish' and tail.high.max() >= boundary):
            return {**result, 'reason': 'Developing leg overlaps wave 1; impulse count invalidated.'}
    return {**result, **count, 'available': True, 'reason': 'Candidate count on completed daily swings.'}
