from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.data.scan_data import DailyScanData


def data(russell=True):
    finnhub = SimpleNamespace(russell_1000_symbols=AsyncMock(return_value={"AAPL"}),
                              market_cap_usd=AsyncMock(return_value=None))
    alpaca = SimpleNamespace(nyse_nasdaq_symbols=AsyncMock(return_value={"AAPL", "TEST"}))
    return DailyScanData(finnhub, alpaca, SimpleNamespace(scan_russell_1000_only=russell))


@pytest.mark.asyncio
async def test_enabled_russell_filter_never_silently_becomes_wide():
    scan = data()
    scan.finnhub.russell_1000_symbols.return_value = set()
    assert await scan._apply_universe_filters({"TEST": "mover"}) == {}
    assert "Russell 1000" in scan.filter_errors[0]


@pytest.mark.asyncio
async def test_explicit_wide_mode_does_not_require_russell_membership():
    scan = data(russell=False)
    assert await scan._apply_universe_filters({"TEST": "mover"}) == {"TEST": "mover"}
    scan.finnhub.russell_1000_symbols.assert_not_awaited()


@pytest.mark.asyncio
async def test_missing_exchange_list_does_not_approve_all_tickers():
    scan = data(russell=False)
    scan.alpaca.nyse_nasdaq_symbols.return_value = set()
    assert await scan._apply_universe_filters({"TEST": "mover"}) == {}
    assert scan.filter_errors


@pytest.mark.asyncio
async def test_cap_filter_excludes_unknown_but_retries_later():
    scan = data()
    scan.alpaca = None
    scan.finnhub.market_cap_usd.side_effect = [None, 600_000_000]
    assert await scan.filter_by_market_cap({"TEST": "mover"}, 500_000_000) == {}
    assert scan.filter_errors
    assert await scan.filter_by_market_cap({"TEST": "mover"}, 500_000_000) == {"TEST": "mover"}
    assert scan.finnhub.market_cap_usd.await_count == 2


@pytest.mark.asyncio
async def test_disabled_cap_filter_does_not_require_cap_lookup():
    scan = data()
    assert await scan.filter_by_market_cap({"TEST": "mover"}, 0) == {"TEST": "mover"}
    scan.finnhub.market_cap_usd.assert_not_awaited()
