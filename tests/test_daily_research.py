from datetime import date, datetime, timedelta, timezone
from unittest.mock import AsyncMock

import httpx
import pytest

from app.config import settings
from app.data.daily_research import DailyResearch, ResearchDataError, normalize_bars, symbols_from_text
import app.data.daily_research as research


def raw(day='2026-10-16', **kwargs):
    return {'t':f'{day}T04:00:00Z', 'o':10, 'h':12, 'l':9, 'c':11, 'v':1000, **kwargs}


def test_normalization_rejects_incomplete_bad_bars_and_deduplicates():
    result = normalize_bars([raw(), raw('2026-10-17'), raw('2026-10-15', c=float('nan')),
                             raw('2026-10-14', c=15), raw(c=11.5)], date(2026, 10, 17))
    assert len(result) == 1
    assert result[0]['time'] == '2026-10-16'
    assert result[0]['close'] == 11.5


def test_symbol_validation():
    assert symbols_from_text('aapl, AAPL brk.b; MSFT') == ['AAPL', 'BRK.B', 'MSFT']
    for bad in ('', '<script>', '../a', 'A' * 12):
        with pytest.raises(ValueError):
            symbols_from_text(bad)


def test_daily_vwap_preserved_when_valid_but_never_invalidates_ohlc():
    assert normalize_bars([raw(vw=10.5)], date(2026,10,17))[0]['vwap'] == 10.5
    for bad in ('invalid',float('nan'),100,None):
        data = normalize_bars([raw(vw=bad)], date(2026,10,17))
        assert len(data) == 1 and data[0]['vwap'] is None


@pytest.mark.asyncio
async def test_history_paginates_split_adjusted_and_caches(monkeypatch):
    monkeypatch.setattr(settings, 'alpaca_api_key', 'test')
    monkeypatch.setattr(settings, 'alpaca_secret_key', 'test')
    client = DailyResearch()
    calls = []

    async def handle(request):
        calls.append(request)
        assert request.url.params['timeframe'] == '1Day'
        assert request.url.params['adjustment'] == 'split'
        if 'page_token' not in request.url.params:
            return httpx.Response(200, json={'bars':{'AAPL':[raw()]}, 'next_page_token':'second'})
        return httpx.Response(200, json={'bars':{'SPY':[raw()]}, 'next_page_token':None})

    await client.http.aclose()
    client.http = httpx.AsyncClient(transport=httpx.MockTransport(handle))
    first = await client.histories(['AAPL', 'SPY'], date(2026, 10, 17))
    second = await client.histories(['AAPL', 'SPY'], date(2026, 10, 17))
    assert first == second and len(calls) == 2
    assert first['SPY']
    await client.close()


@pytest.mark.asyncio
async def test_missing_credentials_explicit_and_provider_errors_redacted(monkeypatch):
    client = DailyResearch()
    monkeypatch.setattr(settings, 'alpaca_api_key', '')
    with pytest.raises(ResearchDataError, match='ALPACA_API_KEY'):
        await client.histories(['AAPL'], date(2026, 10, 17))
    await client.http.aclose()
    client.http = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(403)))
    with pytest.raises(ResearchDataError) as error:
        await client._get('https://example.test/calendar', params={'token':'supersecret'})
    assert 'supersecret' not in str(error.value)
    assert 'denied' in str(error.value)
    await client.close()


@pytest.mark.asyncio
async def test_earnings_uses_dates_not_fiscal_period_and_reports_partial(monkeypatch):
    monkeypatch.setattr(settings, 'finnhub_api_key', 'test')
    client = DailyResearch()
    calls = []

    async def handle(request):
        calls.append(request)
        if len(calls) == 2:
            return httpx.Response(403)
        return httpx.Response(200, json={'earningsCalendar':[
            {'symbol':'AAPL', 'date':'2025-02-01', 'year':2024, 'quarter':4, 'hour':'amc'},
            {'symbol':'MSFT', 'date':'2025-02-01'},
        ]})

    await client.http.aclose()
    client.http = httpx.AsyncClient(transport=httpx.MockTransport(handle))
    data = await client.earnings('AAPL', date(2025, 1, 1), date(2026, 3, 1))
    assert data['status'] == 'partial'
    assert len(data['events']) == 1
    assert data['events'][0]['date'] == '2025-02-01'
    assert data['events'][0]['hour'] == 'amc'
    await client.close()


@pytest.mark.asyncio
async def test_empty_calendar_is_not_a_provider_failure(monkeypatch):
    monkeypatch.setattr(settings, 'finnhub_api_key', 'test')
    client = DailyResearch()
    await client.http.aclose()
    client.http = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={'earningsCalendar':[]})))
    data = await client.earnings(None, date(2026, 10, 17), date(2026, 10, 23))
    assert data['status'] == 'available'
    assert data['events'] == []
    await client.close()


def test_current_bar_normalization_uses_eastern_date_and_rejects_future_or_malformed():
    rows = [raw('2026-10-19'), raw('2026-10-20'), raw(t='2026-10-20T01:00:00Z', c=11.5),
            raw(t=123), raw(t='2026-10-19'), None]
    data = normalize_bars(rows, date(2026, 10, 19), include_current=True)
    assert len(data) == 1 and data[0]['time'] == '2026-10-19'
    assert data[0]['close'] == 11.5


@pytest.mark.asyncio
async def test_snapshots_refresh_independently_of_history_and_share_feed(monkeypatch):
    monkeypatch.setattr(settings, 'alpaca_api_key', 'test')
    monkeypatch.setattr(settings, 'alpaca_secret_key', 'test')
    monkeypatch.setattr(settings, 'alpaca_data_feed', 'iex')
    clock = [100.0]
    monkeypatch.setattr(research, 'monotonic', lambda: clock[0])
    client = DailyResearch()
    calls = []

    async def handle(request):
        calls.append(request.url.path)
        assert request.url.params['feed'] == 'iex'
        if request.url.path.endswith('/bars'):
            return httpx.Response(200, json={'bars': {'AAPL': [raw()]}})
        return httpx.Response(200, json={'AAPL': {'dailyBar': raw('2026-10-19', c=11 + clock[0] / 1000),
                                                'latestTrade': {'t': '2026-10-19T15:00:00Z'}}})

    await client.http.aclose()
    client.http = httpx.AsyncClient(transport=httpx.MockTransport(handle))
    day = date(2026, 10, 19)
    first, meta = await client.current_histories(['AAPL'], day)
    cached, _ = await client.current_histories(['AAPL'], day)
    assert first == cached and len(calls) == 2
    assert meta['AAPL']['status'] == 'provisional'
    assert meta['AAPL']['trade_at'] == '2026-10-19T15:00:00Z'
    assert len(first['AAPL']) == 2
    clock[0] += 31
    refreshed, _ = await client.current_histories(['AAPL'], day)
    assert refreshed['AAPL'][-1]['close'] > first['AAPL'][-1]['close']
    assert len(refreshed['AAPL']) == 2
    assert calls == ['/v2/stocks/bars', '/v2/stocks/snapshots', '/v2/stocks/snapshots']
    assert len((await client.histories(['AAPL'], day))['AAPL']) == 1
    await client.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('payload', [None, {}, {'dailyBar': raw()}, {'dailyBar': raw('2026-10-20')},
                                    {'dailyBar': raw('2026-10-19', c=100)},
                                    {'latestTrade': {'p': 11, 't': '2026-10-19T15:00:00Z'}}])
async def test_missing_today_never_fabricates_or_duplicates_a_candle(monkeypatch, payload):
    client = DailyResearch()
    monkeypatch.setattr(client, 'histories', AsyncMock(return_value={'AAPL': normalize_bars([raw()], date(2026,10,19))}))
    monkeypatch.setattr(client, '_get', AsyncMock(return_value={'AAPL': payload}))
    history, meta = await client.current_histories(['AAPL'], date(2026,10,19))
    assert len(history['AAPL']) == 1
    assert meta['AAPL']['status'] == 'not_returned'
    await client.close()


@pytest.mark.asyncio
async def test_current_day_cache_rolls_over_by_market_date(monkeypatch):
    client = DailyResearch()
    monkeypatch.setattr(client, 'histories', AsyncMock(return_value={'AAPL': []}))
    provider = AsyncMock(side_effect=[{'AAPL': {'dailyBar': raw('2026-10-19')}},
                                     {'AAPL': {'dailyBar': raw('2026-10-19')}}])
    monkeypatch.setattr(client, '_get', provider)
    first, _ = await client.current_histories(['AAPL'], date(2026,10,19))
    next_day, meta = await client.current_histories(['AAPL'], date(2026,10,20))
    assert first['AAPL'] and not next_day['AAPL']
    assert meta['AAPL']['status'] == 'not_returned' and provider.await_count == 2
    await client.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('snapshot_failure', [False, True])
async def test_chart_scan_indicators_and_plan_use_the_same_current_bar(monkeypatch, snapshot_failure):
    day = date(2026,10,19)

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026,10,19,15,tzinfo=timezone.utc).astimezone(tz)

    monkeypatch.setattr(research, 'datetime', Clock)
    monkeypatch.setattr(research, 'market_session', lambda: 'regular')
    client = DailyResearch()
    historical = normalize_bars([raw((day-timedelta(days=i)).isoformat(), v=2000000) for i in range(320,0,-1)], day)
    monkeypatch.setattr(client, 'histories', AsyncMock(return_value={'AAPL': historical, 'SPY': historical}))
    snapshot = {'dailyBar': raw(day.isoformat(), o=12, h=13, c=12.5, v=4000000, vw=12)}
    monkeypatch.setattr(client, '_get', AsyncMock(side_effect=ResearchDataError('Feed denied.') if snapshot_failure else None,
                                               return_value={'AAPL': snapshot, 'SPY': snapshot}))
    monkeypatch.setattr(client, 'earnings', AsyncMock(return_value={'events': [], 'status': 'available'}))
    chart = await client.chart('AAPL', 1, anchor='custom', anchor_date=day.isoformat())
    scan = await client.scan(['AAPL'])
    summary = chart['summary']
    assert scan['items'][0] == summary
    if snapshot_failure:
        assert chart['bars'][-1]['time'] == '2026-10-18'
        assert chart['current_day']['status'] == 'unavailable'
        assert not summary['eligible'] and not summary['provisional']
        assert chart['trade_plan']['status'] == 'unavailable'
        assert scan['current_day_count'] == 0
    else:
        assert chart['bars'][-1]['time'] == summary['as_of'] == day.isoformat()
        assert chart['bars'][-1]['close'] == summary['close'] == 12.5
        assert summary['sma']['20'] == chart['averages']['20'][-1]['value'] == 11.075
        assert chart['avwap']['points'][-1]['value'] == 12
        assert chart['trade_plan']['provisional']
        assert any(e['provisional'] for e in chart['events'])
        assert summary['trigger']['provisional']
        assert scan['current_day_count'] == 1 and scan['refresh_seconds'] == 60
    await client.close()
