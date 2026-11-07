from datetime import date
from itertools import product
from string import ascii_uppercase

import httpx
import numpy as np
import pandas as pd
import pytest

from app.data.index_universes import membership
from app.engine.elliott import classify, combine_degrees, swing_pivots, wave_context
from app.engine.technicals import analyze, chart_payload
from tests.test_technicals import bars


def symbols(n):
    return [''.join(p) for p in product(ascii_uppercase, repeat=2)][:n]


def test_ivv_classes_and_complete_holdings():
    header = 'iShares Core S&P 500 ETF\nFund Holdings as of,"Nov 05, 2026"\nTicker,Asset Class,Market Weight\n'
    text = header + '\n'.join(f'{s},Equity,0.2' for s in symbols(500)) + '\nBRK B,Equity,0.2\nFUT,Futures,1\nABC WS,Equity,-'
    parsed = membership('sp500', httpx.Response(200,text=text), date(2026,11,7))
    assert len(parsed['symbols']) == 501 and 'BRK.B' in parsed['symbols']
    for invalid in [text.replace('Nov 05','Oct 05'), text.replace('Nov 05','Nov 15'), text+'\nAA,Equity,0.2', header+'AA,Equity,100']:
        with pytest.raises(ValueError):
            membership('sp500', httpx.Response(200,text=invalid), date(2026,11,7))


def test_nasdaq_requires_complete_dated_membership():
    data = dict(totalrecords=101,date='Nov 6, 2026',data={'rows':[{'symbol':s} for s in symbols(101)]})
    get = lambda: membership('nasdaq100',httpx.Response(200,json={'data':data}),date(2026,11,7))
    assert len(get()['symbols']) == 101
    data['totalrecords'] = 102
    with pytest.raises(ValueError):
        get()


def swings(prices, bearish=False):
    return [dict(i=i,price=300-v if bearish else v,kind=('high' if (i%2==1) != bearish else 'low'),time=str(i)) for i,v in enumerate(prices)]


@pytest.mark.parametrize('bearish',[False,True])
def test_impulse_and_abc(bearish):
    pivots = swings([100,120,110,145,130,155,137,149,123],bearish)
    for n in range(4,10):
        result = classify(pivots[:n])
        assert result['direction'] == ('bearish' if bearish else 'bullish')
        assert ''.join(p['label'] for p in result['pivots']) == '012345ABC'[:n]
        assert result['retracement2_pct'] == 50
    assert classify(swings([100,120,95,140])) is None
    assert len((classify(swings([100,120,110,140,115])) or {}).get('pivots', [])) < 5
    assert len((classify(swings([100,130,125,145,131,165])) or {}).get('pivots', [])) < 6


def test_pivot_confirmation_lag_and_no_provisional_input():
    closes = np.interp(np.arange(71), [0,5,15,25,35,45,55,65,70], [110,100,120,110,145,130,155,137,144])
    dates = pd.date_range('2026-01-01',periods=len(closes)).strftime('%Y-%m-%d')
    data = pd.DataFrame(dict(time=dates,high=closes+.05,low=closes-.05,atr=1))
    pivots = swing_pivots(data)
    assert all(p['confirmed_on'] == data.time.iloc[p['i']+3] for p in pivots)
    today = date.fromisoformat(dates[-1])
    result = wave_context(data,today)
    assert result['available'] and result['phase'] == 'Correction through A'
    data.loc[data.index[-1],'high'] = 10000
    assert wave_context(data,today) == result
    assert not wave_context(data.head(8),today)['available']


@pytest.mark.parametrize('side,sign',[('bullish',1),('bearish',-1)])
@pytest.mark.parametrize('last_close,points',[(134,0),(140,3),(148,5)])
def test_chart_and_rank_use_same_wave_four_recovery(side, sign, last_close, points):
    values = np.interp(np.arange(55),[0,5,15,25,35,45,54],[110,100,120,110,145,130,last_close])
    closes = np.r_[np.full(230,110.),values]
    rows = bars(closes if sign == 1 else 300-closes)
    today = date(2026,10,17)
    result = analyze('TEST',rows,rows,today)
    wave = chart_payload(rows,1,today)['elliott']
    assert wave['phase']=='Impulse through 4' and wave['direction']==side
    assert result['elliott']['evidence']==wave['evidence']
    assert wave['evidence'][side]==points and wave['evidence']['bearish' if sign==1 else 'bullish']==0
    for breakdown in (result['breakdown'],result['chart_assessment']['breakdown']):
        assert sum(r['maximum'] for r in breakdown)==100
        assert next(r for r in breakdown if r['label']=='Elliott wave context')['maximum']==5
    assert result['score_version']=='daily-v5-elliott'


def test_short_scale_capped_conflict_and_stale_neutral():
    short=dict(available=True,points=5,reason='Recovery',direction='bullish',degree='Short',pivots=[{'label':'4'}])
    assert combine_degrees([short])['bullish']==2
    standard={**short,'degree':'Standard','direction':'bearish'}
    assert combine_degrees([standard,short])['bearish']==combine_degrees([standard,short])['bullish']==0
    assert combine_degrees([standard,short],stale=True)['bullish']==0
    assert combine_degrees([standard],stale=True)['bearish']==0
    assert combine_degrees([{**standard,'direction':'bullish'},short])['bullish']==5


def test_developing_count_is_visible_but_scores_zero():
    values = np.interp(np.arange(33),[0,5,15,25,32],[110,100,120,110,116])
    rows = bars(np.r_[np.full(230,110.),values])
    wave = chart_payload(rows,1,date(2026,10,17))['elliott']
    assert wave['phase']=='Developing 1-2' and wave['extension3'] is None
    assert wave['evidence']['bullish']==wave['evidence']['bearish']==0
    assert wave['sessions']==260


def test_wave_evidence_never_creates_a_setup(monkeypatch):
    import app.engine.technicals as engine
    rows=bars([100.]*240)
    monkeypatch.setattr(engine,'wave_context',lambda *_:dict(phase='Impulse through 4',degree='Standard',
                        as_of=rows[-1]['time'],evidence=dict(bullish=5,bearish=0,detail='Test evidence')))
    r=analyze('TEST',rows,rows,date(2026,10,17))
    assert not r['eligible'] and r['score']==0 and r['trigger'] is None
    assert next(v for v in r['chart_assessment']['breakdown'] if v['label']=='Elliott wave context')['points']==5
