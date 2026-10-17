from datetime import date

import httpx
import pytest

from app.config import settings
from app.data.daily_research import DailyResearch, ResearchDataError, normalize_bars, symbols_from_text


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
