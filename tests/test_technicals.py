from datetime import date

import pandas as pd
import pytest

from app.engine.technicals import analyze, chart_payload, events, frame


def bars(closes, end='2026-10-16', volume=1_000_000):
    dates = pd.bdate_range(end=end, periods=len(closes))
    return [dict(time=d.date().isoformat(), open=float(c), high=float(c) + .5,
                 low=float(c) - .5, close=float(c), volume=volume) for d, c in zip(dates, closes)]


def test_moving_average_warmup_and_sorted_unique_dates():
    data = frame(list(reversed(bars(range(1, 241)))) + bars([240]))
    assert len(data) == 240
    assert pd.isna(data.sma200.iloc[198])
    assert data.sma200.iloc[199] == pytest.approx(100.5)
    assert data.sma20.iloc[-1] == pytest.approx(sum(range(221, 241)) / 20)


@pytest.mark.parametrize('sign,side', [(1, 'bullish'), (-1, 'bearish')])
def test_price_200_cross_requires_close_not_wick(sign, side):
    rows = bars([100.] * 230 + [100 + sign * 3])
    found = events(frame(rows))
    cross = [e for e in found if e['kind'] == 'price200' and e['direction'] == side]
    assert len(cross) == 1 and cross[0]['held']
    rows[-1]['close'] = 100
    assert not [e for e in events(frame(rows)) if e['kind'] == 'price200']


def test_crosses_all_pairs_and_failed_crosses_are_not_held():
    data = frame(bars([100.] * 230 + [103., 97.]))
    found = events(data)
    for kind in ('price200', 'ma20_50', 'ma20_200', 'ma50_200'):
        bullish = [e for e in found if e['kind'] == kind and e['direction'] == 'bullish']
        assert len(bullish) == 1
        assert not bullish[0]['held']


def test_volume_uses_prior_sessions_and_score_components_sum():
    rows = bars([100.] * 230 + [103.])
    rows[-1]['volume'] = 2_000_000
    result = analyze('TEST', rows, bars([100.] * 231), date(2026, 10, 17), [])
    assert result['eligible']
    assert result['direction'] == 'bullish'
    assert result['volume_ratio'] == 2
    components = {r['label']: r for r in result['breakdown']}
    assert components['Trigger-day volume']['points'] == 20
    assert components['Recent held trigger']['points'] == 30  # no stacking correlated crosses
    assert result['score'] == max(0, sum(r['points'] for r in result['breakdown']))
    assert 0 <= result['score'] <= 100


def test_earnings_penalty_and_no_price_floor():
    rows = bars([2.] * 230 + [2.1])
    clean = analyze('CHEAP', rows, [], date(2026, 10, 17), [])
    event = analyze('CHEAP', rows, [], date(2026, 10, 17), [{'date':'2026-10-20'}])
    assert clean['eligible']
    assert clean['score'] - event['score'] == 10
    assert event['next_earnings']['date'] == '2026-10-20'
    assert any('SPY' in w for w in event['warnings'])


def test_no_trigger_insufficient_history_and_stale_are_not_ranked():
    assert not analyze('FLAT', bars([100.] * 240), [], date(2026, 10, 17))['eligible']
    assert not analyze('IPO', bars([100.] * 199), [], date(2026, 10, 17))['eligible']
    rows = bars([100.] * 230 + [103.], end='2026-09-01')
    assert not analyze('STALE', rows, [], date(2026, 10, 17))['eligible']


def test_cross_age_expires_and_benchmark_never_uses_future_rows():
    rows = bars([100.] * 230 + [103.] * 11)
    assert not analyze('OLD', rows, [], date(2026, 10, 17))['eligible']
    current = bars([100.] * 230 + [103.])
    benchmark = bars([100.] * 231)
    future = dict(benchmark[-1], time='2026-10-19', close=10000)
    a = analyze('TEST', current, benchmark, date(2026, 10, 17))
    b = analyze('TEST', current, benchmark + [future], date(2026, 10, 17))
    assert a['score'] == b['score']
    assert a['relative_strength'] == b['relative_strength']


def test_range_levels_exclude_breakout_bar():
    rows = bars([100.] * 230 + [104.])
    found = [e for e in events(frame(rows)) if e['kind'] == 'range55']
    assert len(found) == 1
    assert found[0]['level'] == 100.5


def test_five_year_view_keeps_daily_bars_and_warmed_up_averages():
    rows = bars([100 + i * .01 for i in range(1600)])
    payload = chart_payload(rows, 5, date(2026, 10, 17))
    assert 1250 < len(payload['bars']) < 1350
    assert payload['averages']['200'][0]['time'] == payload['bars'][0]['time']
    assert payload['bars'][-1]['time'] == '2026-10-16'
