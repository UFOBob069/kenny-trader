"""Paper execution with durable intent and broker-authoritative accounting."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from alpaca.common.exceptions import APIError

from app.data.market_hours import ET, market_session, is_extended_hours
from app.engine.execution_policy import paper_execution_allowed, require_paper_execution
from app.engine.reconciliation import reconcile, TERMINAL
from app.models import Direction, SignalStatus, Trade, TradeStatus

log = logging.getLogger(__name__)


class Trader:
    def __init__(self, broker, store, risk):
        self.broker, self.store, self.risk = broker, store, risk
        self._lock = asyncio.Lock()

    def restore_risk(self):
        today = datetime.now(ET).date()
        self.risk._day = today
        self.risk.trades_today = sum(t.opened_at.astimezone(ET).date() == today for t in self.store.trades.values())
        self.risk.realized_pnl_today = sum(t.realized_pnl or 0 for t in self.store.closed_trades()
                                         if t.closed_at and t.closed_at.astimezone(ET).date() == today)
        self.risk.realized_pnl_today += sum(min(0, t.realized_pnl or 0) for t in self.store.open_trades())

    async def execute(self, signal, auto):
        require_paper_execution()
        async with self._lock:
            self.restore_risk()
            existing = next((t for t in self.store.trades.values() if t.signal_id == signal.id), None)
            if existing:
                if existing.status == TradeStatus.CANCELED:
                    return None, 'Previous paper order was canceled or rejected; no resubmission'
                return existing, 'Paper order already recorded'
            if self.store.storage_error:
                return None, self.store.storage_error
            if any(t.reconciliation_error for t in self.store.open_trades()):
                return None, 'Resolve paper reconciliation errors before new entries'
            if any(t.symbol == signal.symbol for t in self.store.open_trades()):
                return None, 'A paper trade already owns this symbol'
            ok, reason = self.risk.can_trade()
            if not ok:
                return None, reason
            qty = self.risk.position_size(signal)
            if qty < 1:
                return None, 'Risk budget is too small for one share'
            try:
                await self.broker.assert_symbol_clear(signal.symbol)
            except Exception:
                return None, 'Broker position/order check failed or symbol is already in use'
            trade = Trade(signal_id=signal.id, symbol=signal.symbol, direction=signal.direction,
                          quantity=qty, entry=signal.entry, stop=signal.stop, target=signal.target,
                          confidence=signal.confidence, setup=signal.setup.value,
                          strategy_version='morning-v1', signal_snapshot=signal.model_dump(mode='json'),
                          status=TradeStatus.SUBMITTING, broker_account_id=self.broker.account_id,
                          pending_exits=is_extended_hours())
            trade.client_order_id = 'kt-' + trade.id
            self.store.save_trade(trade)
            self.restore_risk()
            try:
                placement = await self.broker.place_bracket(signal.symbol, signal.direction, qty,
                    signal.entry, signal.stop, signal.target, client_order_id=trade.client_order_id)
                trade.order_ids = placement.order_ids
                trade.pending_exits = placement.pending_exits
                trade.status = TradeStatus.PENDING
                self.store.save_trade(trade)
                signal.status = SignalStatus.AUTO_EXECUTED if auto else SignalStatus.APPROVED
                self.store.save_signal(signal)
                await self._sync(trade)
            except Exception as exc:
                trade.reconciliation_error = 'Submission outcome needs broker reconciliation; not retried'
                if isinstance(exc, APIError) and exc.status_code in (400, 401, 403, 422):
                    try:
                        found = await self.broker.order_by_client_id(trade.client_order_id)
                        if not found:
                            trade.status = TradeStatus.CANCELED
                            trade.exit_reason = 'submission_rejected'
                            trade.reconciliation_error = None
                            signal.status = SignalStatus.REJECTED
                            self.store.save_signal(signal)
                    except Exception:
                        pass  # Unknown is safer than declaring a timeout/retry canceled.
                self.store.save_trade(trade)
                log.exception('Paper submission requires reconciliation')
            if trade.status == TradeStatus.CANCELED:
                return None, 'Paper entry rejected or canceled without a fill'
            return trade, 'Paper order recorded; outcome follows confirmed broker fills'

    async def _sync(self, trade):
        try:
            orders = await self.broker.trade_orders(trade)
            reconcile(trade, orders)
            trade.protection_warning = None
            close_order = trade.orders.get(trade.close_order_id)
            if close_order and close_order['status'] in TERMINAL and trade.remaining_quantity:
                raise ValueError('Close order ended with shares remaining; inspect Alpaca paper position')
            if trade.status not in (TradeStatus.CLOSED, TradeStatus.CANCELED):
                signed = trade.remaining_quantity * (1 if trade.direction == Direction.LONG else -1)
                position = await self.broker.position_quantity(trade.symbol)
                if abs(position - signed) > 1e-8:
                    raise ValueError('Broker position differs from attributed fills; external activity or fill race')
            if trade.remaining_quantity and not trade.close_requested:
                entry = trade.orders[trade.order_ids[0]]
                active_stops = [o for o in orders if o['id'] != entry['id'] and 'stop' in o['type'] and o['status'] not in TERMINAL]
                if entry['status'] not in TERMINAL or not active_stops or market_session() != 'regular':
                    trade.protection_warning = 'Stop protection not confirmed for this session/quantity; inspect Alpaca paper account'
            if trade.pending_exits and trade.remaining_quantity and not trade.close_requested:
                entry = trade.orders[trade.order_ids[0]]
                if entry['status'] in TERMINAL and market_session() == 'regular':
                    ids = await self.broker.attach_exit_orders(trade.symbol, trade.direction,
                        trade.remaining_quantity, trade.stop, trade.target, client_order_id='kt-' + trade.id + '-exits')
                    trade.order_ids.extend(i for i in ids if i not in trade.order_ids)
                    trade.pending_exits = False
                else:
                    trade.reconciliation_error = 'Filled shares await exits; extended-hours stops unavailable or entry partially filled'
            if trade.remaining_quantity:
                trade.current_price = await self.broker.last_price(trade.symbol)
        except Exception as exc:
            trade.pnl_verified = False
            trade.reconciliation_error = str(exc) if isinstance(exc, ValueError) else 'Broker reconciliation unavailable; retry pending'
            log.warning('Paper reconciliation unresolved for %s', trade.id)
        self.store.save_trade(trade)

    async def close(self, trade, exit_price=None):
        require_paper_execution()
        async with self._lock:
            if trade.status == TradeStatus.UNATTRIBUTED:
                raise ValueError('Historical record cannot authorize a broker close; manage any existing position in Alpaca')
            if trade.status in (TradeStatus.CLOSED, TradeStatus.CANCELED):
                return trade
            await self._sync(trade)
            if trade.status in (TradeStatus.CLOSED, TradeStatus.CANCELED):
                return trade
            if trade.reconciliation_error and not trade.pending_exits:
                raise ValueError(trade.reconciliation_error)
            if trade.close_order_id:
                return trade
            trade.close_requested = True
            trade.close_client_order_id = 'kt-' + trade.id + '-close'
            self.store.save_trade(trade)
            await self.broker.cancel_trade_orders(list(trade.orders.values()))
            for _ in range(5):
                await self._sync(trade)
                if trade.reconciliation_error:
                    raise ValueError(trade.reconciliation_error)
                if all(o['status'] in TERMINAL for o in trade.orders.values()):
                    break
                await asyncio.sleep(.2)
            else:
                raise ValueError('Cancellation pending; no close order submitted. Retry after confirmation.')
            if trade.remaining_quantity:
                trade.close_order_id = await self.broker.close_position(trade.symbol, trade.direction,
                    trade.remaining_quantity, client_order_id=trade.close_client_order_id)
                trade.status = TradeStatus.CLOSING
                self.store.save_trade(trade)
                await self._sync(trade)
            self.restore_risk()
            return trade

    async def refresh_marks(self):
        if not paper_execution_allowed():
            return
        async with self._lock:
            for trade in self.store.open_trades():
                await self._sync(trade)
            self.restore_risk()
