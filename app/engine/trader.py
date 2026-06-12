"""Trade execution and open-position monitoring."""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from app.data.alpaca import BrokerClient
from app.db.store import MemoryStore
from app.engine.risk import RiskManager
from app.models import Direction, Signal, SignalStatus, Trade, TradeStatus

log = logging.getLogger(__name__)


class Trader:
    def __init__(self, broker: BrokerClient, store: MemoryStore, risk: RiskManager) -> None:
        self.broker = broker
        self.store = store
        self.risk = risk

    async def execute(self, signal: Signal, auto: bool) -> Trade | None:
        ok, reason = self.risk.can_trade()
        if not ok:
            log.warning("Trade blocked for %s: %s", signal.symbol, reason)
            signal.status = SignalStatus.REJECTED
            self.store.save_signal(signal)
            return None

        qty = self.risk.position_size(signal)
        if qty < 1:
            log.warning("Position size 0 for %s (risk/share %.2f too wide)", signal.symbol, signal.risk_per_share)
            signal.status = SignalStatus.REJECTED
            self.store.save_signal(signal)
            return None

        try:
            placement = await self.broker.place_bracket(
                signal.symbol, signal.direction, qty, signal.entry, signal.stop, signal.target
            )
        except Exception:
            log.exception("Order failed for %s", signal.symbol)
            signal.status = SignalStatus.REJECTED
            self.store.save_signal(signal)
            return None

        signal.status = SignalStatus.AUTO_EXECUTED if auto else SignalStatus.APPROVED
        self.store.save_signal(signal)

        trade = Trade(
            signal_id=signal.id,
            symbol=signal.symbol,
            direction=signal.direction,
            quantity=qty,
            entry=signal.entry,
            stop=signal.stop,
            target=signal.target,
            confidence=signal.confidence,
            order_ids=placement.order_ids,
            pending_exits=placement.pending_exits,
        )
        self.store.save_trade(trade)
        if not placement.pending_exits:
            self.risk.record_trade_opened()
        log.info("Trade opened: %s %s x%d @ %.2f (conf %.0f%%)",
                 trade.direction.value, trade.symbol, qty, trade.entry, trade.confidence)
        return trade

    async def close(self, trade: Trade, exit_price: float | None = None) -> Trade:
        self.broker.cancel_orders(trade.order_ids)
        await self.broker.close_position(trade.symbol, trade.direction, trade.quantity)
        price = exit_price or await self.broker.last_price(trade.symbol) or trade.entry
        sign = 1 if trade.direction == Direction.LONG else -1
        trade.exit_price = price
        trade.realized_pnl = round(sign * (price - trade.entry) * trade.quantity, 2)
        trade.status = TradeStatus.CLOSED
        trade.closed_at = datetime.now(timezone.utc)
        self.store.save_trade(trade)
        self.risk.record_trade_closed(trade.realized_pnl)
        log.info("Trade closed: %s P&L $%.2f", trade.symbol, trade.realized_pnl)
        return trade

    async def refresh_marks(self) -> None:
        """Update marks and attach stop/target after extended-hours entries fill."""
        open_trades = self.store.open_trades()
        pending_before = {t.id: t.pending_exits for t in open_trades}
        await self.broker.sync_pending_exits(open_trades)

        for trade in open_trades:
            was_pending = pending_before.get(trade.id, False)
            if was_pending and not trade.pending_exits:
                if len(trade.order_ids) > 1:
                    self.risk.record_trade_opened()
                else:
                    trade.status = TradeStatus.CLOSED
                    trade.closed_at = datetime.now(timezone.utc)
                self.store.save_trade(trade)
                continue
            if trade.pending_exits:
                continue
            price = await self.broker.last_price(trade.symbol)
            if price:
                trade.current_price = price
                self.store.save_trade(trade)
