"""Trade execution and open-position monitoring."""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from app.data.ibkr import IbkrClient
from app.db.store import MemoryStore
from app.engine.risk import RiskManager
from app.models import Direction, Signal, SignalStatus, Trade, TradeStatus

log = logging.getLogger(__name__)


class Trader:
    def __init__(self, ibkr: IbkrClient, store: MemoryStore, risk: RiskManager) -> None:
        self.ibkr = ibkr
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

        order_ids = await self.ibkr.place_bracket(
            signal.symbol, signal.direction, qty, signal.entry, signal.stop, signal.target
        )

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
            ib_order_ids=order_ids,
        )
        self.store.save_trade(trade)
        self.risk.record_trade_opened()
        log.info("Trade opened: %s %s x%d @ %.2f (conf %.0f%%)",
                 trade.direction.value, trade.symbol, qty, trade.entry, trade.confidence)
        return trade

    async def close(self, trade: Trade, exit_price: float | None = None) -> Trade:
        self.ibkr.cancel_orders(trade.ib_order_ids)
        await self.ibkr.close_position(trade.symbol, trade.direction, trade.quantity)
        price = exit_price or await self.ibkr.last_price(trade.symbol) or trade.entry
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
        """Update current prices on open trades and detect bracket fills that
        closed a position on the IB side."""
        for trade in self.store.open_trades():
            price = await self.ibkr.last_price(trade.symbol)
            if price:
                trade.current_price = price
                self.store.save_trade(trade)
