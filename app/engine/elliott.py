"""A conservative single-degree Elliott interpretation; not a predictive model."""
from datetime import date

import numpy as np
from numpy.lib.stride_tricks import sliding_window_view


def swing_pivots(data, wing=3, fraction=.03, atr_factor=1.5):
    width = 2 * wing + 1
    if len(data) < width:
        return []
    dates = data.time.to_numpy()
    atr = data.atr.to_numpy()
    candidates = []
    for kind, values in [('high', data.high.to_numpy()), ('low', data.low.to_numpy())]:
        windows = sliding_window_view(values, width)
        extreme = windows.max(axis=1) if kind == 'high' else windows.min(axis=1)
        unique = (windows == extreme[:, None]).sum(axis=1) == 1
        for index in np.flatnonzero(unique & (windows[:, wing] == extreme)) + wing:
            candidates.append((int(index), kind, float(values[index])))
    swings = []
    counts = {}
    for i, _, _ in candidates:
        counts[i] = counts.get(i, 0) + 1
    for i, kind, price in sorted(candidates):
        if counts[i] != 1:  # Outside bars have ambiguous intraday ordering.
            continue
        pivot = dict(i=i, kind=kind, price=price, time=dates[i], confirmed_on=dates[i+wing])
        if swings:
            prev = swings[-1]
            sign = 1 if kind == 'high' else -1
            move = sign * (price - prev['price'])
            if prev['kind'] == kind:
                if move > 0:
                    swings[-1] = pivot
                continue
            if move < max(prev['price'] * fraction, atr_factor * atr[i] if np.isfinite(atr[i]) else 0):
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


def _degree(closed, name, params):
    swings = swing_pivots(closed, *params)
    result = dict(degree=name, available=False, phase='Unclassified', points=0,
                  reason='Latest swings do not fit an impulse.', swing_count=len(swings), pivots=[])
    if len(closed) < 30:
        return {**result, 'reason': 'Insufficient completed sessions (need 30).'}
    if len(swings) < 3:
        return {**result, 'reason': 'Fewer than three qualifying swing pivots.'}
    count = classify(swings)
    if not count:
        p = swings[-3:]
        sign = 1 if p[0]['kind'] == 'low' else -1
        a,b,c = [sign * x['price'] for x in p]
        if not a < c < b:
            return result
        count = dict(direction='bullish' if sign == 1 else 'bearish', phase='Developing 1-2',
                     retracement2_pct=round(100*(b-c)/(b-a),1), extension3=None,
                     pivots=[{**x, 'label':label} for x,label in zip(p,'012')])
    last = count['pivots'][-1]
    if len(closed)-1-last['i'] > 20:
        return {**result, 'reason':'Latest pivot is more than 20 sessions old.'}
    label = last['label']
    sign = 1 if count['direction'] == 'bullish' else -1
    p = count['pivots']
    adverse = closed.low if sign == 1 else -closed.high
    def breached(start, end, boundary):
        stop = p[end]['i']+1 if len(p) > end else len(closed)
        return adverse.iloc[p[start]['i']+1:stop].min() <= sign*p[boundary]['price']

    if breached(1,3,0):
        return {**result, 'reason':'Origin breached; developing count invalidated.'}
    if len(p) >= 4 and breached(3,5,1):
        return {**result, 'reason':'Wave 1 overlap; impulse count invalidated.'}
    if label == '4' and adverse.iloc[last['i']+1:].min() < sign*last['price']:
        return {**result, 'reason':'Wave 4 pivot no longer holds; awaiting a new pivot.'}
    points = 0
    reason = 'Late impulse or correction; no continuation or reversal credit.'
    if label in '234':
        if label == '2':
            reason = 'Possible first impulse and pullback; wave 3 not confirmed.'
        elif label == '3':
            points, reason = 2, 'Wave 3 extended beyond wave 1; wave 1 territory still holds.'
        else:
            close = closed.close.iloc[-1]
            points = 5 if sign*(close-p[3]['price']) > 0 else 3 if sign*(close-(last['price']+p[3]['price'])/2) > 0 else 0
            reason = {5:'After wave 4, close cleared the wave 3 extreme.',
                      3:'After wave 4, close recovered over half the pullback.',
                      0:'Wave 4 holds, but no recovery beyond the pullback midpoint.'}[points]
    return {**result, **count, 'available':True, 'reason':reason, 'points':points}


def combine_degrees(degrees, stale=False):
    # Use one scale, never sum correlated counts. Earlier and shorter counts
    # remain visible without being treated as equally strong evidence.
    active = [d for d in degrees if d['available'] and d['pivots'][-1]['label'] in '234']
    credited = next((d for d in degrees if d['points']), None)
    summary = dict(bullish=0, bearish=0, maximum=5)
    if stale:
        detail = 'Completed history is stale; no wave credit.'
    elif len({d['direction'] for d in active}) > 1:
        detail = 'Active swing scales disagree; no directional credit.'
    elif credited:
        points = min(2, credited['points']) if credited['degree'] == 'Short' else credited['points']
        summary[credited['direction']] = points
        detail = f"{credited['degree']} scale, {credited['direction']} +{points}: {credited['reason']}"
    else:
        chosen = next((d for d in degrees if d['available']), degrees[0])
        detail = chosen['reason']
    return {**summary, 'detail':detail}


def wave_context(data, today):
    closed = data if data.empty else data[data.time < today.isoformat()].tail(260)
    degrees = [_degree(closed, 'Standard', (3,.03,1.5)), _degree(closed, 'Short', (2,.02,1.0))]
    # Prefer the existing standard count; an established short count is more
    # informative to plot than a merely developing standard count.
    selected = next((d for d in degrees if d['available'] and len(d['pivots']) >= 4),
                    next((d for d in degrees if d['available']), degrees[0]))
    as_of = closed.time.iloc[-1] if len(closed) else None
    score = combine_degrees(degrees, as_of is not None and (today-date.fromisoformat(as_of)).days > 5)
    return {**selected, 'as_of':as_of, 'sessions':len(closed), 'degrees':degrees, 'evidence':score}
