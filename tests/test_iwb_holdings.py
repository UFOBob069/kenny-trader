import csv
from datetime import date
from io import StringIO
from itertools import islice, product

import httpx
import pytest

from app.data.iwb_holdings import IwbHoldings, parse_holdings


def document(day='Oct 15, 2026', count=1000, weight='0.1'):
    out = StringIO()
    writer = csv.writer(out)
    writer.writerow(['iShares Russell 1000 ETF'])
    writer.writerow(['Fund Holdings as of', day])
    writer.writerow(['Ticker', 'Name', 'Asset Class', 'Weight (%)'])
    for letters in islice(product('ABCDEFGHIJKLMNOPQRSTUVWXYZ', repeat=3), count):
        writer.writerow([''.join(letters), 'Quoted, Company', 'Equity', weight])
    writer.writerow(['USD', 'Cash', 'Cash', '0.1'])
    return out.getvalue()


def test_issuer_csv_date_equity_and_quoted_fields():
    symbols, day = parse_holdings('\ufeff' + document(), date(2026, 10, 17))
    assert len(symbols) == 1000
    assert 'AAA' in symbols and 'USD' not in symbols
    assert day == date(2026, 10, 15)


@pytest.mark.parametrize('body', [
    '', '\n', '<html>denied</html>', document('Oct 1, 2026'),
    document('Oct 18, 2026'), document('invalid'), document(count=100),
    document(weight='0.01'), document(weight='nan'), document(weight='bad'),
    document().replace('Fund Holdings as of', 'Unknown date'),
], ids=['empty', 'blank', 'html', 'stale', 'future', 'bad-date', 'truncated',
        'low-weight', 'nan-weight', 'bad-weight', 'missing-date'])
def test_unverified_or_partial_holdings_fail_closed(body):
    with pytest.raises(ValueError):
        parse_holdings(body, date(2026, 10, 17))


@pytest.mark.asyncio
async def test_daily_cache_and_failed_refresh_do_not_return_stale_membership(monkeypatch):
    monkeypatch.setattr('app.data.iwb_holdings.trading_date', lambda: date(2026, 10, 17))
    calls = []

    def respond(request):
        calls.append(request)
        return httpx.Response(200, text=document()) if len(calls) == 1 else httpx.Response(503)

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
        source = IwbHoldings(http)
        assert len(await source.symbols()) == 1000
        assert len(await source.symbols()) == 1000
        assert len(calls) == 1
        monkeypatch.setattr('app.data.iwb_holdings.trading_date', lambda: date(2026, 10, 18))
        assert await source.symbols() == set()
        assert source.status['state'] == 'unavailable'
        assert await source.symbols() == set()
        assert len(calls) == 2  # Negative-cache failures instead of hammering the issuer.


@pytest.mark.asyncio
async def test_finnhub_membership_uses_issuer_without_finnhub_credentials(monkeypatch):
    from app.config import settings
    from app.data.finnhub import FinnhubClient
    monkeypatch.setattr(settings, 'finnhub_api_key', '')
    monkeypatch.setattr('app.data.iwb_holdings.trading_date', lambda: date(2026, 10, 17))
    client = FinnhubClient()
    await client._http.aclose()
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, text=document()))) as http:
        client._membership.http = http
        assert len(await client.russell_1000_symbols()) == 1000
        assert client.membership_status['as_of'] == '2026-10-15'


@pytest.mark.asyncio
async def test_finnhub_error_diagnostics_redact_token(monkeypatch, caplog):
    from app.config import settings
    from app.data.finnhub import FinnhubClient
    monkeypatch.setattr(settings, 'finnhub_api_key', 'audit-secret-never-log')
    client = FinnhubClient()
    await client._http.aclose()
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(403))) as http:
        client._http = http
        assert await client._get('/calendar/earnings') == {}
        assert client.errors['/calendar/earnings'] == 'Finnhub subscription access denied'
        assert 'audit-secret-never-log' not in caplog.text
