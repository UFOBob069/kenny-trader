from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.data.alpaca import AlpacaClient
from app.data.market_hours import ET


def raw(ts, volume=100):
    return SimpleNamespace(timestamp=ts, open=10, high=11, low=9, close=10, volume=volume)


@pytest.mark.asyncio
async def test_daily_average_excludes_current_day_and_is_cached():
    client = AlpacaClient()
    now = datetime.now(timezone.utc)
    history = [raw(now - timedelta(days=1), 200), raw(now - timedelta(days=2), 100), raw(now, 10000)]
    client._data = Mock()
    client._data.get_stock_bars.return_value = SimpleNamespace(data={"TEST": history})
    assert await client._avg_daily_volume("TEST") == 150
    assert await client._avg_daily_volume("TEST") == 150
    client._data.get_stock_bars.assert_called_once()
    request = client._data.get_stock_bars.call_args.args[0]
    assert request.feed == client._feed


@pytest.mark.asyncio
async def test_prior_session_is_one_day_not_all_returned_history():
    client = AlpacaClient()
    now = datetime.now(ET).replace(hour=14, minute=0, second=0, microsecond=0)
    history = [raw(now - timedelta(days=4)), raw(now - timedelta(days=3)), raw(now - timedelta(days=1))]
    client._data = Mock()
    client._data.get_stock_bars.return_value = SimpleNamespace(data={"TEST": history})
    prior, today = await client.prior_session_bars("TEST")
    assert len(prior) == 1 and prior[0].ts == history[-1].timestamp
    assert today == []


@pytest.mark.asyncio
async def test_last_price_uses_same_feed_as_chart():
    client = AlpacaClient()
    client._data = Mock()
    client._data.get_stock_latest_trade.return_value = {"TEST": SimpleNamespace(price=10)}
    assert await client.last_price("TEST") == 10
    request = client._data.get_stock_latest_trade.call_args.args[0]
    assert request.feed == client._feed


@pytest.mark.asyncio
async def test_bid_ask_preserves_feed_and_source_timestamp():
    client = AlpacaClient()
    now = datetime.now(timezone.utc)
    client._data = Mock()
    client._data.get_stock_latest_quote.return_value = {"TEST": SimpleNamespace(bid_price=1.5, ask_price=1.51, timestamp=now)}
    assert await client.bid_ask("TEST") == {"bid": 1.5, "ask": 1.51, "quote_at": now}
    request = client._data.get_stock_latest_quote.call_args.args[0]
    assert request.feed == client._feed


@pytest.mark.asyncio
async def test_batch_fetch_uses_single_request_for_all_symbols(monkeypatch):
    import app.data.alpaca as module
    now = datetime(2026, 9, 8, 14, tzinfo=timezone.utc)

    class FixedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return now.astimezone(tz)

    monkeypatch.setattr(module, "datetime", FixedDatetime)
    client = AlpacaClient()
    client._data = Mock()
    client._data.get_stock_bars.return_value = SimpleNamespace(data={"AAA": [raw(now - timedelta(minutes=1))], "BBB": []})
    batch = await client.minute_bars_many(["AAA", "BBB"])
    assert len(batch["AAA"]) == 1 and batch["BBB"] == []
    client._data.get_stock_bars.assert_called_once()
    request = client._data.get_stock_bars.call_args.args[0]
    assert request.symbol_or_symbols == ["AAA", "BBB"]
    assert request.feed == client._feed
    # Alpaca's request model normalizes aware timestamps to naive UTC.
    assert request.start == datetime(2026, 9, 8, 8)
