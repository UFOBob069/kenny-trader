from datetime import date
import json

import numpy as np
import pandas as pd
import pytest

from app.engine.technicals import analyze, chart_payload, frame
from app.engine.volatility import volatility_context, volatility_payload, volatility_score
from tests.test_technicals import bars


def test_bollinger_population_std_and_prior_donchian_levels():
    rows = bars([100 + i for i in range(40)])
    data = frame(rows)
    window = np.array([b['close'] for b in rows[-20:]])
    assert data.bb_middle.iloc[-1] == pytest.approx(window.mean())
    assert data.bb_upper.iloc[-1] == pytest.approx(window.mean() + 2 * window.std(ddof=0))
    assert data.bb_lower.iloc[-1] == pytest.approx(window.mean() - 2 * window.std(ddof=0))
    assert data.dc_upper.iloc[-1] == max(b['high'] for b in rows[-21:-1])
    assert data.dc_lower.iloc[-1] == min(b['low'] for b in rows[-21:-1])
    rows[-1]['high'] = 1000
    assert frame(rows).dc_upper.iloc[-1] == data.dc_upper.iloc[-1]


def test_squeeze_formula_and_regression_match_reference():
    data = frame(bars([100 + np.sin(i / 5) for i in range(80)]))
    assert data.squeeze_on.iloc[-1] == (data.bb_upper.iloc[-1] < data.kc_upper.iloc[-1] and data.bb_lower.iloc[-1] > data.kc_lower.iloc[-1])
    middle = (data.high.rolling(20).max() + data.low.rolling(20).min()) / 2
    delta = data.close - (middle + data.close.rolling(20).mean()) / 2
    slope, intercept = np.polyfit(np.arange(20), delta.iloc[-20:], 1)
    assert data.squeeze_momentum.iloc[-1] == pytest.approx(intercept + slope * 19)
    from ta.volatility import AverageTrueRange
    expected = data.close.ewm(span=20, min_periods=20, adjust=False).mean() + 1.5 * AverageTrueRange(data.high, data.low, data.close, 20).average_true_range()
    assert data.kc_upper.iloc[-1] == pytest.approx(expected.iloc[-1])


@pytest.mark.parametrize('count', [1, 5, 13, 14, 19, 20, 38, 39])
def test_warmup_never_fakes_zero_indicator_values(count):
    data = frame(bars([100.] * count))
    payload = volatility_payload(data)
    assert len(payload['atr']) == max(0, count - 13)
    assert len(payload['bollinger']['upper']) == max(0, count - 19)
    assert len(payload['donchian']['upper']) == max(0, count - 20)
    assert len(payload['momentum']) == max(0, count - 38)
    assert len(payload['squeeze']) == max(0, count - 19)
    json.dumps(payload, allow_nan=False)
    json.dumps(volatility_context(data), allow_nan=False)


def test_atr_wilder_smoothing_and_decline():
    rows = bars([100.] * 50)
    for i, row in enumerate(rows):
        spread = 4 if i < 30 else .2
        row.update(high=100 + spread, low=100 - spread)
    data = frame(rows)
    expected = 8.
    for row in rows[14:]:
        expected = (expected * 13 + row['high'] - row['low']) / 14
    assert data.atr.iloc[-1] == pytest.approx(expected)
    assert volatility_context(data)['atr_change5_pct'] < 0


def test_atr_includes_gaps_not_only_intraday_range():
    rows = bars([100.] * 20 + [110.])
    data = frame(rows)
    assert data.atr.iloc[-1] == pytest.approx((13 * 1 + 10.5) / 14)


@pytest.mark.parametrize('sign', [1, -1])
def test_directional_release_and_donchian_confirmation(sign):
    data = frame(bars([100.] * 250 + [100 + sign * 20]))
    assert data.squeeze_on.iloc[-2]
    assert data.squeeze_release.iloc[-1]
    points = {row[0]: row[1] for row in volatility_score(data, sign)}
    opposite = {row[0]: row[1] for row in volatility_score(data, -sign)}
    assert points['Donchian breakout confirmation'] == 5
    assert points['Squeeze release confirmation'] == 5
    assert opposite['Donchian breakout confirmation'] == 0
    assert opposite['Squeeze release confirmation'] == 0
    data.loc[data.index[-1], 'squeeze_on'] = True
    assert volatility_score(data, sign)[2][1] == 0  # a new squeeze cancels release credit
    data.loc[data.index[-1], 'squeeze_on'] = False
    data.loc[:, 'squeeze_release'] = False
    data.loc[data.index[-6], 'squeeze_release'] = True
    assert volatility_score(data, sign)[2][1] == 0  # release evidence expires


def test_compression_is_neutral_and_does_not_qualify_an_entry():
    rows = bars([100.] * 250)
    for i, row in enumerate(rows):
        spread = 2 if i < 220 else .5
        row.update(high=100+spread, low=100-spread)
    data = frame(rows)
    assert volatility_score(data, 1)[0][1] == volatility_score(data, -1)[0][1] == 5
    summary = analyze('TIGHT', rows, rows, date(2026,10,17))
    assert not summary['eligible'] and summary['score'] == 0
    assert summary['chart_assessment']['bullish_score'] == summary['chart_assessment']['bearish_score']
    assert sum(row['maximum'] for row in summary['breakdown']) == 100


def test_indicators_have_no_future_leakage_and_ranges_keep_warmup():
    rows = bars([100 + np.sin(i / 5) for i in range(400)])
    prefix = frame(rows[:-1])
    full = frame(rows)
    pd.testing.assert_frame_equal(prefix, full.iloc[:-1])
    payload = chart_payload(rows, 1, date(2026,10,17))
    for name in ('bollinger','donchian','keltner'):
        assert payload['studies'][name]['upper'][0]['time'] == payload['bars'][0]['time']
        assert payload['studies'][name]['upper'][-1]['time'] == payload['bars'][-1]['time']
    json.dumps(payload, allow_nan=False)
