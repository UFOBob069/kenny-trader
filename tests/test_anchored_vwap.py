from datetime import date

import pandas as pd
import pytest

from app.engine.anchored_vwap import anchored_vwap, discovery_context, select_anchor
from app.engine.technicals import analyze, chart_payload, frame


def rows(closes, volumes=None):
    dates = pd.bdate_range(end='2026-10-16', periods=len(closes))
    return [dict(time=d.date().isoformat(), open=c, close=c, high=c+1, low=c-1,
                 volume=volumes[i] if volumes else 1000000) for i,(d,c) in enumerate(zip(dates,closes))]


def test_volume_weighted_daily_provider_prices_and_zero_volume():
    data = rows([10,20,30], [1,3,0])
    for row in data:
        row['vwap'] = row['close']
    result = anchored_vwap(frame(data), 'custom', data[0]['time'])
    assert result['series'].tolist() == [10,17.5,17.5]
    assert result['method'] == 'Provider daily VWAP x volume'
    assert result['distance_pct'] == pytest.approx((30/17.5-1)*100, abs=.01)


def test_missing_provider_vwap_uses_consistent_hlc3_estimate():
    data = rows([10,20], [1,3])
    data[0]['vwap'] = 9.5
    result = anchored_vwap(frame(data),'custom',data[0]['time'])
    assert result['value'] == 17.5
    assert result['method'] == 'Daily HLC3 estimate'
    zero = anchored_vwap(frame(rows([10,20],[0,0])),'ytd')
    assert zero['value'] is None and zero['series'].isna().all()


def test_pivot_needs_five_later_sessions_and_uses_highest_confirmed_peak():
    data = frame(rows([100]*8 + [120] + [100]*4))
    assert not select_anchor(data,'swing_high')['available']
    data = frame(rows([100]*8 + [120] + [100]*6 + [110] + [100]*5))
    anchor = select_anchor(data,'swing_high')
    assert anchor['index'] == 8 and anchor['confirmed_index'] == 13
    assert anchor['confirmed_at'] == data.time.iloc[13]
    lows = frame(rows([100]*8+[80]+[100]*5))
    assert select_anchor(lows,'swing_low')['index'] == 8


def test_no_reclaim_signal_before_anchor_confirmation():
    data = frame(rows([100]*8+[120]+[100,100,119,100,100,100,119]))
    result = anchored_vwap(data)
    assert all(e['index'] > result['anchor']['confirmed_index'] for e in result['events'])
    reclaims = [e for e in result['events'] if e['direction'] == 'bullish']
    assert reclaims and reclaims[-1]['held']


def test_earnings_before_open_and_after_close_map_to_different_sessions():
    data = frame(rows([100]*30))
    friday = data.time.iloc[-6]
    before = select_anchor(data,'earnings',earnings=[{'date':friday,'hour':'bmo'}])
    after = select_anchor(data,'earnings',earnings=[{'date':friday,'hour':'amc'}])
    assert before['date'] == friday
    assert after['date'] == data.time.iloc[-5]
    assert not select_anchor(data,'earnings',earnings=[{'date':friday,'hour':'unknown'}])['available']
    assert not select_anchor(data,'earnings',earnings=[{'date':'2027-01-01','hour':'bmo'}])['available']


def test_custom_anchor_does_not_reset_when_display_range_changes():
    data = rows([100 + i*.01 for i in range(1600)])
    anchor_date = data[-700]['time']
    a = chart_payload(data,1,date(2026,10,17),'custom',anchor_date)
    b = chart_payload(data,5,date(2026,10,17),'custom',anchor_date)
    assert a['avwap']['value'] == b['avwap']['value']
    assert a['avwap']['anchor']['date'] == b['avwap']['anchor']['date']
    assert a['avwap']['points'][-1] == b['avwap']['points'][-1]
    assert not select_anchor(frame(data),'custom','1990-01-01')['available']


def test_price_discovery_distinguishes_52_week_from_fetched_history():
    data = frame(rows([200]*10+[100]*260+[120]))
    result = discovery_context(data)
    assert result['above_52w'] and not result['above_history']
    assert result['history_high'] == 201
    data = frame(rows([100]*260+[120]))
    result = discovery_context(data)
    assert result['above_history'] and result['above_52w']
    assert 'all-time' not in result['state'].lower()
    assert not discovery_context(frame(rows([100]*30+[120])))['above_history']


def test_avwap_score_budget_and_reclaim_is_rankable():
    data = rows([100]*230+[120]+[100]*7+[115])
    result = analyze('TEST',data,[],date(2026,10,17),[])
    assert result['eligible']
    assert any(e['kind']=='avwap' and e['held'] for e in result['signals'])
    assert sum(c['maximum'] for c in result['breakdown']) == 100
    assert any(c['label']=='Peak anchored VWAP' and c['points'] > 0 for c in result['breakdown'])
