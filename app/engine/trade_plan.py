"""Deterministic daily research plans, not executable broker orders."""
from datetime import date
import math


def daily_trade_plan(summary: dict, bars: list[dict], today: date) -> dict:
    base = dict(version='daily-plan-v1', status='unavailable', as_of=summary.get('as_of'),
                direction=summary.get('direction'), warnings=[], reasons=[], execution='research_only')
    if not bars or not summary.get('eligible') or summary.get('score', 0) < 50 or not summary.get('trigger'):
        return {**base, 'reasons': ['No qualifying recent held signal with score at least 50.']}
    atr = summary.get('atr')
    if not atr or not math.isfinite(atr) or atr <= 0:
        return {**base, 'reasons': ['Valid ATR is unavailable.']}
    if (today - date.fromisoformat(summary['as_of'])).days > 3:
        return {**base, 'reasons': ['History is over three calendar days old; refresh before planning.']}
    long = summary['direction'] == 'bullish'
    sign = 1 if long else -1
    last = bars[-1]
    level = summary['trigger']['level']
    if level is None or not math.isfinite(level) or level <= 0:
        return {**base, 'reasons': ['Trigger price unavailable.']}
    tick = .0001 if last['close'] < 1 else .01

    def rounded(value, up):
        return round((math.ceil(value / tick) if up else math.floor(value / tick)) * tick, 4)

    entry = rounded((max(last['high'], level) if long else min(last['low'], level)) + sign * .1 * atr, long)
    structure = min(b['low'] for b in bars[-5:]) if long else max(b['high'] for b in bars[-5:])
    stop = rounded(min(structure - .25 * atr, entry - atr) if long else max(structure + .25 * atr, entry + atr), not long)
    risk = abs(entry - stop)
    target = rounded(entry + sign * 2 * risk, long)
    if min(entry, stop, target) <= 0 or not risk:
        return {**base, 'reasons': ['Price structure cannot support valid positive entry, stop and target levels.']}
    obstacles = [b['high' if long else 'low'] for b in bars[-60:-1] if sign * (b['high' if long else 'low'] - entry) > 0]
    obstacle = min(obstacles) if long and obstacles else max(obstacles) if obstacles else None
    room_r = round(abs(obstacle - entry) / risk, 2) if obstacle else None
    warnings = ['Research plan; no order submitted. Stops can fill beyond their trigger after a gap.',
                'Daily turnover does not verify live spreads or executable liquidity.']
    reasons = []
    if summary.get('next_earnings'):
        days = (date.fromisoformat(summary['next_earnings']['date']) - today).days
        if 0 <= days <= 2:
            reasons.append('Earnings within two calendar days; wait until after the event.')
        elif days <= 7:
            warnings.append('Earnings within seven days; overnight gap risk.')
    else:
        warnings.append('Upcoming earnings date unconfirmed; check before entry.')
    if not long:
        warnings.append('Short idea requires borrow availability; losses are not capped by the stop.')
    if room_r is not None and room_r < 1.5:
        reasons.append('Nearby prior price structure leaves less than 1.5R of room.')
    if risk / entry > .08:
        reasons.append('Stop distance exceeds 8%; wait for a tighter setup.')
    if abs(last['close'] - summary.get('sma', {}).get('20', last['close'])) > 3 * atr:
        reasons.append('More than 3 ATR from SMA 20; wait for consolidation.')
    return {**base, 'status': 'wait' if reasons else 'conditional', 'entry': entry, 'stop': stop,
            'target': target, 'reward_risk': round(abs(target - entry) / risk, 2),
            'risk_per_share': round(risk, 4), 'risk_pct': round(risk / entry * 100, 2),
            'entry_rule': f"{'Long above' if long else 'Short below'} the latest daily {'high' if long else 'low'} / trigger, plus 0.1 ATR. Skip a gap beyond entry by more than 0.25 ATR.",
            'stop_rule': 'Beyond the five-session extreme by 0.25 ATR, at least 1 ATR from entry.',
            'target_rule': '2R planning objective, not a price forecast.',
            'trigger': summary['trigger']['label'], 'atr': atr, 'structure': structure,
            'nearby_level': obstacle, 'room_r': room_r, 'reasons': reasons, 'warnings': warnings,
            'validity': 'Recalculate after the next completed daily bar; no live quote check.'}
