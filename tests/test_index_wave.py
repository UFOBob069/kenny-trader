from datetime import date
from itertools import product
from string import ascii_uppercase

import httpx
import numpy as np
import pandas as pd
import pytest

from app.data.index_universes import membership
from app.engine.elliott import classify, swing_pivots, wave_context


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
