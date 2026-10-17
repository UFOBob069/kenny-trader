"""Interactive Brokers connection: market data, bars, bracket orders, positions."""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from ib_async import IB, Contract, Stock, util

from app.data.orders import OrderPlacement
from app.data.bar_sessions import split_sessions
from app.config import settings
from app.models import Bar, Direction

log = logging.getLogger(__name__)


class IbkrClient:
    def __init__(self) -> None:
        self.ib = IB()

    async def connect(self) -> None:
        if self.ib.isConnected():
            return
        await self.ib.connectAsync(settings.ibkr_host, settings.ibkr_port,
                                   clientId=settings.ibkr_client_id, readonly=True)
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
        """Latest completed prior session and current Eastern calendar day."""
        bars = await self.minute_bars(symbol, days=10)
        return split_sessions(bars, datetime.now(timezone.utc))

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

    async def bid_ask(self, symbol: str) -> dict | None:
        contract = self._stock(symbol)
        await self.ib.qualifyContractsAsync(contract)
        tickers = await self.ib.reqTickersAsync(contract)
        if not tickers:
            return None
        ticker = tickers[0]
        return {"bid": ticker.bid, "ask": ticker.ask, "quote_at": ticker.time}

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
        """Execution is intentionally unavailable on this adapter."""
        raise PermissionError("IBKR execution is disabled; this release supports Alpaca paper only.")

    async def sync_pending_exits(self, trades: list) -> None:
        pass  # IBKR brackets include exits at submission

    async def close_position(self, symbol: str, direction: Direction, quantity: int) -> str:
        raise PermissionError("IBKR execution is disabled; manage positions in the broker.")

    def cancel_orders(self, order_ids: list[str]) -> None:
        raise PermissionError("IBKR execution is disabled; manage orders in the broker.")

    async def account_summary(self) -> dict:
        rows = await self.ib.accountSummaryAsync()
        return {r.tag: r.value for r in rows}
