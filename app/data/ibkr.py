"""Interactive Brokers connection: market data, bars, bracket orders, positions."""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from ib_async import IB, Contract, LimitOrder, Order, Stock, StopOrder, util

from app.data.orders import OrderPlacement
from app.config import settings
from app.models import Bar, Direction

log = logging.getLogger(__name__)


class IbkrClient:
    def __init__(self) -> None:
        self.ib = IB()

    async def connect(self) -> None:
        if self.ib.isConnected():
            return
        await self.ib.connectAsync(settings.ibkr_host, settings.ibkr_port, clientId=settings.ibkr_client_id)
        log.info("Connected to IBKR %s:%s", settings.ibkr_host, settings.ibkr_port)

    def disconnect(self) -> None:
        if self.ib.isConnected():
            self.ib.disconnect()

    # ------------------------------------------------------------------ #

    def _stock(self, symbol: str) -> Contract:
        return Stock(symbol, "SMART", "USD")

    async def minute_bars(self, symbol: str, days: int = 1) -> list[Bar]:
        """Historical 1-minute bars including extended hours."""
        contract = self._stock(symbol)
        await self.ib.qualifyContractsAsync(contract)
        raw = await self.ib.reqHistoricalDataAsync(
            contract,
            endDateTime="",
            durationStr=f"{days} D",
            barSizeSetting="1 min",
            whatToShow="TRADES",
            useRTH=False,
            formatDate=2,
        )
        return [
            Bar(
                ts=b.date if isinstance(b.date, datetime) else datetime.fromtimestamp(int(b.date), tz=timezone.utc),
                open=b.open, high=b.high, low=b.low, close=b.close, volume=float(b.volume),
            )
            for b in raw
        ]

    async def prior_session_bars(self, symbol: str) -> tuple[list[Bar], list[Bar]]:
        """(prior_day_bars, today_bars) split on calendar date of the last bar."""
        bars = await self.minute_bars(symbol, days=2)
        if not bars:
            return [], []
        last_day = bars[-1].ts.date()
        prior = [b for b in bars if b.ts.date() != last_day]
        today = [b for b in bars if b.ts.date() == last_day]
        return prior, today

    async def last_price(self, symbol: str) -> float | None:
        contract = self._stock(symbol)
        await self.ib.qualifyContractsAsync(contract)
        ticker = self.ib.reqMktData(contract, "", snapshot=True)
        for _ in range(20):
            await util.sleep(0.25)
            price = ticker.last or ticker.close
            if price and price > 0:
                return float(price)
        return None

    # ------------------------------------------------------------------ #

    async def place_bracket(
        self,
        symbol: str,
        direction: Direction,
        quantity: int,
        entry: float,
        stop: float,
        target: float,
    ) -> OrderPlacement:
        """Limit entry + OCA stop-loss and take-profit. Works outside RTH."""
        contract = self._stock(symbol)
        await self.ib.qualifyContractsAsync(contract)

        action = "BUY" if direction == Direction.LONG else "SELL"
        reverse = "SELL" if direction == Direction.LONG else "BUY"

        parent = LimitOrder(action, quantity, round(entry, 2))
        parent.outsideRth = True
        parent.transmit = False

        take_profit: Order = LimitOrder(reverse, quantity, round(target, 2))
        stop_loss: Order = StopOrder(reverse, quantity, round(stop, 2))

        trades = []
        parent_trade = self.ib.placeOrder(contract, parent)
        trades.append(parent_trade)
        for i, child in enumerate((take_profit, stop_loss)):
            child.parentId = parent_trade.order.orderId
            child.outsideRth = True
            child.transmit = i == 1  # transmit the whole bracket with the last child
            trades.append(self.ib.placeOrder(contract, child))

        ids = [str(t.order.orderId) for t in trades]
        log.info("Bracket placed %s %s x%d entry=%.2f stop=%.2f target=%.2f ids=%s",
                 action, symbol, quantity, entry, stop, target, ids)
        return OrderPlacement(order_ids=ids)

    async def sync_pending_exits(self, trades: list) -> None:
        pass  # IBKR brackets include exits at submission

    async def close_position(self, symbol: str, direction: Direction, quantity: int) -> str:
        contract = self._stock(symbol)
        await self.ib.qualifyContractsAsync(contract)
        action = "SELL" if direction == Direction.LONG else "BUY"
        order = Order(action=action, totalQuantity=quantity, orderType="MKT", outsideRth=True)
        trade = self.ib.placeOrder(contract, order)
        return str(trade.order.orderId)

    def cancel_orders(self, order_ids: list[str]) -> None:
        want = {oid for oid in order_ids}
        for t in self.ib.openTrades():
            if str(t.order.orderId) in want:
                self.ib.cancelOrder(t.order)

    async def account_summary(self) -> dict:
        rows = await self.ib.accountSummaryAsync()
        return {r.tag: r.value for r in rows}
