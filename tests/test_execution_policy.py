from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.config import Settings, settings
from app.data.alpaca import AlpacaClient
from app.data.ibkr import IbkrClient
from app.data.orders import OrderPlacement
from app.db.store import MemoryStore
from app.engine.risk import RiskManager, RuntimeRules
from app.engine.trader import Trader
from app.models import Direction, SetupType, Signal


@pytest.fixture(autouse=True)
def paper_mode(monkeypatch):
    monkeypatch.setattr(settings, 'execution_mode', 'paper')
    monkeypatch.setattr(settings, 'broker', 'alpaca')


def test_live_is_not_a_supported_configuration():
    with pytest.raises(ValidationError):
        Settings(execution_mode='live', _env_file=None)


def test_settings_validation_is_atomic_and_cannot_replace_methods():
    rules = RuntimeRules(settings)
    original = rules.risk_per_trade
    for patch in [{'risk_per_trade': 50, 'max_daily_loss': -1}, {'auto_trade_enabled': 'false'},
                  {'min_market_cap_millions': float('nan')}, {'update': 'replace'}]:
        with pytest.raises(ValueError):
            rules.update(patch)
        assert rules.risk_per_trade == original


@pytest.mark.asyncio
async def test_legacy_live_flag_cannot_select_live_transport(monkeypatch):
    monkeypatch.setattr(settings, 'alpaca_paper', False)
    monkeypatch.setattr(settings, 'alpaca_api_key', 'test')
    monkeypatch.setattr(settings, 'alpaca_secret_key', 'test')
    trading = Mock(_base_url='https://paper-api.alpaca.markets')
    trading.get_account.return_value = SimpleNamespace(id='paper-account', equity='100', cash='100', buying_power='100', portfolio_value='100')
    factory = Mock(return_value=trading)
    monkeypatch.setattr('app.data.alpaca.TradingClient', factory)
    client = AlpacaClient()
    await client.connect()
    assert factory.call_args.kwargs['paper'] is True
    assert client.paper_verified
    client._require_paper()
    trading._base_url = 'https://api.alpaca.markets'
    with pytest.raises(PermissionError):
        client._require_paper()


@pytest.mark.asyncio
@pytest.mark.parametrize('mode,verified,url', [
    ('research', True, 'https://paper-api.alpaca.markets'),
    ('paper', False, 'https://paper-api.alpaca.markets'),
    ('paper', True, 'https://api.alpaca.markets'),
])
async def test_every_alpaca_mutation_checks_mode_and_actual_transport(monkeypatch, mode, verified, url):
    monkeypatch.setattr(settings, 'execution_mode', mode)
    client = AlpacaClient()
    client._trading = Mock(_base_url=url)
    client.paper_verified = verified
    args = ('TEST', Direction.LONG, 1, 10, 9, 12)
    for call in [lambda: client.place_bracket(*args), lambda: client._place_regular_bracket(*args),
                 lambda: client._place_extended_entry(*args),
                 lambda: client.attach_exit_orders('TEST', Direction.LONG, 1, 9, 12),
                 lambda: client.close_position('TEST', Direction.LONG, 1),
                 lambda: client.sync_pending_exits([])]:
        with pytest.raises(PermissionError):
            await call()
    with pytest.raises(PermissionError):
        client.cancel_orders(['test'])
    assert not client._trading.method_calls


@pytest.mark.asyncio
async def test_ibkr_orders_cannot_bypass_paper_boundary():
    client = IbkrClient.__new__(IbkrClient)
    client.ib = Mock()
    with pytest.raises(PermissionError):
        await client.place_bracket('TEST', Direction.LONG, 1, 10, 9, 12)
    with pytest.raises(PermissionError):
        await client.close_position('TEST', Direction.LONG, 1)
    with pytest.raises(PermissionError):
        client.cancel_orders(['test'])
    assert not client.ib.method_calls


def test_research_mode_rejects_api_mutations_before_order_services(monkeypatch):
    from app.api import server
    monkeypatch.setattr(settings, 'execution_mode', 'research')
    approve = AsyncMock()
    close = AsyncMock()
    monkeypatch.setattr(server.orch, 'approve_signal', approve)
    monkeypatch.setattr(server.orch, 'close_trade', close)
    client = TestClient(server.app)  # No lifespan: no broker or background loops.
    try:
        for path in ['/api/signals/audit/approve', '/api/trades/audit/close', '/api/automation/toggle']:
            assert client.post(path).status_code == 403
        for payload in [{'execution_mode': 'live'}, {'alpaca_paper': False}, {'auto_trade_enabled': True}]:
            assert client.put('/api/settings', json=payload).status_code == 422
        assert client.post('/api/automation/disable').json()['auto_trade_enabled'] is False
        approve.assert_not_awaited()
        close.assert_not_awaited()
    finally:
        client.close()


@pytest.mark.asyncio
async def test_pending_entries_reserve_slots_and_fills_do_not_count_twice():
    rules = RuntimeRules(settings)
    rules.max_trades_per_day = 2
    risk = RiskManager(rules)
    broker = Mock()
    broker.account_id = 'paper-account'
    broker.assert_symbol_clear = AsyncMock()
    broker.position_quantity = AsyncMock(return_value=0)
    async def snapshots(trade):
        return [dict(id='entry', symbol=trade.symbol, side='buy', type='limit', status='new',
                     filled_qty=0, filled_avg_price=None, filled_at=None)]
    broker.trade_orders = AsyncMock(side_effect=snapshots)
    broker.place_bracket = AsyncMock(return_value=OrderPlacement(['entry'], pending_exits=True))
    store = MemoryStore()
    trader = Trader(broker, store, risk)
    for symbol in ['AAA', 'BBB', 'CCC']:
        sig = Signal(symbol=symbol, direction=Direction.LONG, setup=SetupType.FAUX_SHOW_BRO,
                     entry=10, stop=9, target=12)
        await trader.execute(sig, auto=True)
    assert broker.place_bracket.await_count == 2
    assert risk.trades_today == 2

    await trader.refresh_marks()
    assert risk.trades_today == 2
