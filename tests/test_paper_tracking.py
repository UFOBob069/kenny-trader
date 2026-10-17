import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, Mock
from types import SimpleNamespace

import pytest

from app.config import settings
from app.data.orders import OrderPlacement
from app.db.store import MemoryStore, SQLiteStore, SupabaseStore
from app.engine.reconciliation import reconcile
from app.engine.risk import RiskManager, RuntimeRules
from app.engine.trader import Trader
from app.models import Trade, TradeStatus, Signal, Direction, SetupType


def trade(**kw):
    return Trade(**dict(signal_id='signal', symbol='TEST', direction='LONG', quantity=10,
                        entry=100, stop=98, target=104, confidence=92, order_ids=['entry'],
                        setup='FAUX_SHOW_BRO', strategy_version='morning-v1', broker_account_id='paper', **kw))


def order(id='entry', side='buy', qty=10, price=100.2, status='filled', type='limit'):
    return dict(id=id, symbol='TEST', side=side, filled_qty=qty, filled_avg_price=price,
                status=status, type=type, filled_at=datetime.now(timezone.utc).isoformat() if qty else None)


def closed_orders():
    return [order(), order('tp', 'sell', 10, 104), order('sl', 'sell', 0, None, 'canceled', 'stop')]


def runner(store=None):
    broker = Mock(account_id='paper')
    broker.trade_orders = AsyncMock(return_value=[order(qty=0, price=None, status='new')])
    broker.position_quantity = AsyncMock(return_value=0)
    broker.assert_symbol_clear = AsyncMock()
    broker.place_bracket = AsyncMock(return_value=OrderPlacement(['entry']))
    broker.last_price = AsyncMock(return_value=103)
    broker.cancel_trade_orders = AsyncMock()
    broker.close_position = AsyncMock(return_value='close')
    broker.attach_exit_orders = AsyncMock(return_value=['oco'])
    rules = RuntimeRules(settings)
    return Trader(broker, store or MemoryStore(), RiskManager(rules)), broker


def test_fill_prices_not_planned_prices_and_repeated_polls_are_idempotent():
    t = trade()
    for _ in range(3):
        reconcile(t, closed_orders())
    assert t.status == TradeStatus.CLOSED and t.pnl_verified
    assert t.entry == 100 and t.entry_fill_price == 100.2
    assert t.realized_pnl == 38 and t.realized_r == 1.9
    assert t.exit_reason == 'target'


def test_partial_entry_and_partial_exits_use_actual_filled_quantities():
    t = trade()
    reconcile(t, [order(qty=4, status='partially_filled')])
    assert t.status == TradeStatus.OPEN and t.filled_quantity == 4 and not t.pnl_verified
    reconcile(t, [order(qty=4, status='canceled'), order('exit', 'sell', 2, 102, 'partially_filled')])
    assert t.remaining_quantity == 2 and t.realized_pnl == 3.6
    reconcile(t, [order(qty=4, status='canceled'), order('exit', 'sell', 4, 103)])
    assert t.pnl_verified and t.realized_pnl == 11.2


def test_short_stop_loss_and_weighted_multiple_exits():
    t = trade()
    t.direction = Direction.SHORT
    reconcile(t, [order(side='sell', price=100), order('first', 'buy', 4, 98), order('stop', 'buy', 6, 103, type='stop')])
    assert t.exit_price == 101 and t.realized_pnl == -10 and t.exit_reason == 'stop'


@pytest.mark.parametrize('status', ['canceled', 'expired', 'rejected'])
def test_unfilled_orders_are_not_trades_or_losses(status):
    t = trade()
    reconcile(t, [order(qty=0, price=None, status=status)])
    store = MemoryStore()
    store.save_trade(t)
    assert t.status == TradeStatus.CANCELED and t.realized_pnl is None
    assert store.pnl_summary()['lifetime']['trades'] == 0
    assert store.performance()['canceled'] == 1


@pytest.mark.parametrize('bad', [order(qty=-1), order(price=None), order(price=float('nan')),
                                order(side='sell')])
def test_invalid_broker_fills_do_not_verify(bad):
    t = trade()
    with pytest.raises(ValueError):
        reconcile(t, [bad])
    assert not t.pnl_verified


def test_over_exit_or_missing_timestamp_cannot_verify():
    t = trade()
    with pytest.raises(ValueError):
        reconcile(t, [order(), order('exit', 'sell', 11, 104)])
    orders = closed_orders()
    orders[1]['filled_at'] = None
    with pytest.raises(ValueError):
        reconcile(t, orders)
    assert not t.pnl_verified


def test_duplicate_nested_order_is_not_counted_twice():
    t = trade()
    orders = closed_orders()
    reconcile(t, orders + [orders[1]])
    assert t.exited_quantity == 10 and t.realized_pnl == 38


def test_statistics_exclude_legacy_and_group_setup_version():
    store = MemoryStore()
    t = trade()
    reconcile(t, closed_orders())
    store.save_trade(t)
    legacy = trade(status='CLOSED', realized_pnl=900)
    store.save_trade(legacy)
    result = store.performance()
    assert result['excluded'] == 1 and result['verified_closed'] == 1
    assert result['groups'][0]['pnl'] == 38 and result['groups'][0]['sample_label'] == 'Small sample'
    assert store.pnl_summary()['lifetime']['pnl'] == 38


def test_sqlite_restores_attribution_snapshots_and_fills(tmp_path):
    path = str(tmp_path / 'paper.sqlite3')
    store = SQLiteStore(path)
    t = trade()
    reconcile(t, closed_orders())
    store.save_trade(t)
    store._db.close()
    restored = SQLiteStore(path)
    assert restored.get_trade(t.id).orders == t.orders
    assert restored.performance()['groups'][0]['pnl'] == 38
    restored._db.close()


@pytest.mark.asyncio
async def test_auto_bracket_exit_reconciles_without_manual_close():
    trader, broker = runner()
    t = trade()
    trader.store.save_trade(t)
    broker.trade_orders.return_value = closed_orders()
    await trader.refresh_marks()
    await trader.refresh_marks()
    assert t.pnl_verified and trader.risk.realized_pnl_today == 38
    broker.close_position.assert_not_awaited()


@pytest.mark.asyncio
async def test_reconciliation_outage_keeps_trade_open_and_blocks_new_orders():
    trader, broker = runner()
    t = trade()
    trader.store.save_trade(t)
    broker.trade_orders.side_effect = RuntimeError('provider down')
    await trader.refresh_marks()
    assert t.status == TradeStatus.OPEN and t.reconciliation_error
    sig = Signal(symbol='OTHER', direction='LONG', setup='FAUX_SHOW_BRO', entry=100, stop=99, target=103)
    result, reason = await trader.execute(sig, False)
    assert result is None and 'reconciliation' in reason
    broker.place_bracket.assert_not_awaited()


@pytest.mark.asyncio
async def test_close_waits_for_fill_and_is_concurrently_idempotent():
    trader, broker = runner()
    t = trade()
    trader.store.save_trade(t)
    broker.position_quantity.return_value = 10
    state = [order()]
    async def snapshots(t):
        return state + ([order('close', 'sell', 0, None, 'new')] if t.close_order_id else [])
    broker.trade_orders.side_effect = snapshots
    await asyncio.gather(trader.close(t, exit_price=999), trader.close(t))
    assert broker.close_position.await_count == 1
    assert t.status == TradeStatus.CLOSING and t.realized_pnl is None
    broker.trade_orders.side_effect = None
    broker.trade_orders.return_value = [order(), order('close', 'sell', 10, 101)]
    await trader.refresh_marks()
    assert t.realized_pnl == 8 and t.exit_reason == 'manual'


@pytest.mark.asyncio
async def test_cancel_unfilled_entry_never_places_opposite_order():
    trader, broker = runner()
    t = trade()
    trader.store.save_trade(t)
    broker.trade_orders.side_effect = [[order(qty=0, price=None, status='new')], [order(qty=0, price=None, status='canceled')]]
    await trader.close(t)
    assert t.status == TradeStatus.CANCELED
    broker.close_position.assert_not_awaited()


@pytest.mark.asyncio
async def test_fill_during_cancel_uses_remaining_quantity():
    trader, broker = runner()
    t = trade()
    trader.store.save_trade(t)
    broker.position_quantity.side_effect = [10, 6, 6]
    broker.trade_orders.side_effect = [[order(), order('exit', 'sell', 0, None, 'new')],
                                     [order(), order('exit', 'sell', 4, 104, 'canceled')],
                                     [order(), order('exit', 'sell', 4, 104, 'canceled'), order('close', 'sell', 0, None, 'new')]]
    await trader.close(t)
    assert broker.close_position.call_args.args[2] == 6


@pytest.mark.asyncio
async def test_persistence_failure_prevents_submission():
    trader, broker = runner()
    trader.store.save_trade = Mock(side_effect=RuntimeError('disk full'))
    sig = Signal(symbol='TEST', direction='LONG', setup='FAUX_SHOW_BRO', entry=100, stop=99, target=103)
    with pytest.raises(RuntimeError):
        await trader.execute(sig, True)
    broker.place_bracket.assert_not_awaited()


@pytest.mark.asyncio
async def test_restart_restores_limits_without_double_counting(tmp_path):
    store = SQLiteStore(str(tmp_path / 'paper.db'))
    t = trade()
    reconcile(t, closed_orders())
    store.save_trade(t)
    restored, broker = runner(SQLiteStore(str(tmp_path / 'paper.db')))
    restored.restore_risk()
    assert restored.risk.trades_today == 1 and restored.risk.realized_pnl_today == 38
    await restored.refresh_marks()
    assert restored.risk.trades_today == 1 and restored.risk.realized_pnl_today == 38
    store._db.close()
    restored.store._db.close()


def test_supabase_hydrates_journal_and_excludes_legacy_estimates(monkeypatch):
    t = trade()
    reconcile(t, closed_orders())
    legacy = trade(status='CLOSED', realized_pnl=999)
    db = Mock()
    tables = {}
    for name, rows in [('settings', [{'key':'paper.trade.' + t.id, 'value':t.model_dump(mode='json')}]),
                       ('trades', [legacy.model_dump(mode='json')])]:
        query = Mock()
        for method in ['select', 'like', 'order', 'range', 'upsert']:
            getattr(query, method).return_value = query
        query.execute.return_value = SimpleNamespace(data=rows)
        tables[name] = query
    db.table.side_effect = lambda name: tables[name]
    monkeypatch.setattr('supabase.create_client', lambda *args: db)
    store = SupabaseStore()
    assert store.performance()['verified_closed'] == 1
    assert store.performance()['excluded'] == 1
    tables['settings'].execute.side_effect = RuntimeError('offline')
    with pytest.raises(RuntimeError, match='journal write failed'):
        store.save_trade(t)
    assert store.storage_error


@pytest.mark.asyncio
async def test_ambiguous_submission_is_not_retried_on_repeat_approval():
    trader, broker = runner()
    broker.place_bracket.side_effect = TimeoutError()
    sig = Signal(symbol='TEST', direction='LONG', setup='FAUX_SHOW_BRO', entry=100, stop=99, target=103)
    first, _ = await trader.execute(sig, True)
    again, _ = await trader.execute(sig, True)
    assert first.id == again.id and broker.place_bracket.await_count == 1
    assert first.status == TradeStatus.SUBMITTING and first.reconciliation_error


@pytest.mark.asyncio
async def test_external_position_change_is_not_guessed_as_profit():
    trader, broker = runner()
    t = trade()
    trader.store.save_trade(t)
    broker.trade_orders.return_value = [order()]
    broker.position_quantity.return_value = 0
    await trader.refresh_marks()
    assert not t.pnl_verified and t.realized_pnl is None and t.reconciliation_error
    with pytest.raises(ValueError):
        await trader.close(t)
    broker.close_position.assert_not_awaited()


@pytest.mark.asyncio
async def test_terminal_partial_extended_entry_protects_actual_quantity(monkeypatch):
    monkeypatch.setattr('app.engine.trader.market_session', lambda: 'regular')
    trader, broker = runner()
    t = trade(pending_exits=True)
    broker.trade_orders.return_value = [order(qty=4, status='canceled')]
    broker.position_quantity.return_value = 4
    trader.store.save_trade(t)
    await trader.refresh_marks()
    assert broker.attach_exit_orders.call_args.args[2] == 4
    assert broker.attach_exit_orders.call_args.kwargs['client_order_id'] == 'kt-' + t.id + '-exits'


@pytest.mark.asyncio
async def test_adapter_recovers_entry_and_nested_legs_by_client_id():
    from app.data.alpaca import AlpacaClient
    client = AlpacaClient()
    client.account_id = 'paper'
    client.paper_verified = True
    client._trading = Mock(_base_url='https://paper-api.alpaca.markets')
    t = trade(client_order_id='kt-recover')
    t.order_ids = []
    entry = {**order(), 'legs': closed_orders()[1:]}
    client.order_by_client_id = AsyncMock(return_value=entry)
    client._trading.get_order_by_id.return_value = entry
    rows = await client.trade_orders(t)
    assert t.order_ids == ['entry'] and len(rows) == 3
    reconcile(t, rows)
    assert t.pnl_verified and t.realized_pnl == 38
    client._trading.submit_order.assert_not_called()


@pytest.mark.asyncio
async def test_adapter_rejects_different_account_before_reading_orders():
    from app.data.alpaca import AlpacaClient
    client = AlpacaClient()
    client.paper_verified = True
    client.account_id = 'different'
    client._trading = Mock(_base_url='https://paper-api.alpaca.markets')
    with pytest.raises(ValueError, match='different-account'):
        await client.trade_orders(trade())
    client._trading.get_order_by_id.assert_not_called()
