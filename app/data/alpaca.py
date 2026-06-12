"""Alpaca Markets client: bars, quotes, bracket orders (paper or live)."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Protocol
from zoneinfo import ZoneInfo

from alpaca.data.enums import DataFeed
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.historical.screener import ScreenerClient
from alpaca.data.requests import (
    MarketMoversRequest,
    StockBarsRequest,
    StockLatestQuoteRequest,
    StockLatestTradeRequest,
    StockSnapshotRequest,
)
from alpaca.data.timeframe import TimeFrame
from alpaca.trading.client import TradingClient
from alpaca.trading.enums import OrderClass, OrderSide, OrderStatus, QueryOrderStatus, TimeInForce
from alpaca.trading.requests import LimitOrderRequest, StopLossRequest, TakeProfitRequest

from app.config import settings
from app.data.market_hours import is_extended_hours
from app.data.orders import OrderPlacement
from app.models import Bar, Direction, Trade

log = logging.getLogger(__name__)
ET = ZoneInfo("America/New_York")
_TERMINAL = {
    OrderStatus.CANCELED,
    OrderStatus.EXPIRED,
    OrderStatus.REJECTED,
    OrderStatus.FILLED,
}


class BrokerClient(Protocol):
    async def connect(self) -> None: ...
    def disconnect(self) -> None: ...
    async def minute_bars(self, symbol: str, days: int = 1) -> list[Bar]: ...
    async def prior_session_bars(self, symbol: str) -> tuple[list[Bar], list[Bar]]: ...
    async def last_price(self, symbol: str) -> float | None: ...
    async def place_bracket(
        self,
        symbol: str,
        direction: Direction,
        quantity: int,
        entry: float,
        stop: float,
        target: float,
    ) -> OrderPlacement: ...
    async def close_position(self, symbol: str, direction: Direction, quantity: int) -> str: ...
    def cancel_orders(self, order_ids: list[str]) -> None: ...
    async def sync_pending_exits(self, trades: list[Trade]) -> None: ...


class AlpacaClient:
    def __init__(self) -> None:
        self._trading: TradingClient | None = None
        self._data: StockHistoricalDataClient | None = None
        self._screener: ScreenerClient | None = None
        feed_name = settings.alpaca_data_feed.lower()
        self._feed = DataFeed.SIP if feed_name == "sip" else DataFeed.IEX

    async def connect(self) -> None:
        if not settings.alpaca_api_key or not settings.alpaca_secret_key:
            raise ValueError("ALPACA_API_KEY and ALPACA_SECRET_KEY are required")
        self._trading = TradingClient(
            settings.alpaca_api_key,
            settings.alpaca_secret_key,
            paper=settings.alpaca_paper,
        )
        self._data = StockHistoricalDataClient(
            settings.alpaca_api_key,
            settings.alpaca_secret_key,
        )
        self._screener = ScreenerClient(
            settings.alpaca_api_key,
            settings.alpaca_secret_key,
        )
        account = await asyncio.to_thread(self._trading.get_account)
        mode = "paper" if settings.alpaca_paper else "live"
        log.info("Connected to Alpaca (%s) — equity $%s", mode, account.equity)

    def disconnect(self) -> None:
        self._trading = None
        self._data = None
        self._screener = None

    async def minute_bars(self, symbol: str, days: int = 1) -> list[Bar]:
        if not self._data:
            return []
        end = datetime.now(timezone.utc)
        start = end - timedelta(days=days)
        request = StockBarsRequest(
            symbol_or_symbols=symbol.upper(),
            timeframe=TimeFrame.Minute,
            start=start,
            end=end,
            feed=self._feed,
        )
        try:
            response = await asyncio.to_thread(self._data.get_stock_bars, request)
        except Exception:
            log.exception("Alpaca bars request failed for %s", symbol)
            return []
        raw = response.data.get(symbol.upper(), [])
        return [_to_bar(b) for b in raw]

    async def prior_session_bars(self, symbol: str) -> tuple[list[Bar], list[Bar]]:
        bars = await self.minute_bars(symbol, days=2)
        if not bars:
            return [], []
        last_day = bars[-1].ts.astimezone(ET).date()
        prior = [b for b in bars if b.ts.astimezone(ET).date() != last_day]
        today = [b for b in bars if b.ts.astimezone(ET).date() == last_day]
        return prior, today

    async def last_price(self, symbol: str) -> float | None:
        if not self._data:
            return None
        sym = symbol.upper()
        try:
            trades = await asyncio.to_thread(
                self._data.get_stock_latest_trade,
                StockLatestTradeRequest(symbol_or_symbols=sym),
            )
            trade = trades.get(sym)
            if trade and trade.price and trade.price > 0:
                return float(trade.price)
        except Exception:
            log.debug("Latest trade unavailable for %s, falling back to quote", symbol)
        try:
            quotes = await asyncio.to_thread(
                self._data.get_stock_latest_quote,
                StockLatestQuoteRequest(symbol_or_symbols=sym),
            )
        except Exception:
            log.exception("Alpaca quote request failed for %s", symbol)
            return None
        quote = quotes.get(sym)
        if not quote:
            return None
        for price in (quote.ask_price, quote.bid_price):
            if price and price > 0:
                return float(price)
        return None

    async def market_movers(self, top: int = 25) -> list[str]:
        """Top gainers + losers for today's scan list."""
        if not self._screener:
            return []
        try:
            movers = await asyncio.to_thread(
                self._screener.get_market_movers,
                MarketMoversRequest(top=top),
            )
        except Exception:
            log.exception("Alpaca market movers request failed")
            return []
        symbols: list[str] = []
        for group in (getattr(movers, "gainers", None), getattr(movers, "losers", None)):
            if not group:
                continue
            for item in group:
                sym = getattr(item, "symbol", None)
                if sym:
                    symbols.append(sym.upper())
        return symbols

    async def quote_snapshot(self, symbol: str) -> dict | None:
        """Price, prior close, today's volume, and 20-day avg volume for scanning."""
        if not self._data:
            return None
        sym = symbol.upper()
        try:
            snaps = await asyncio.to_thread(
                self._data.get_stock_snapshot,
                StockSnapshotRequest(symbol_or_symbols=sym),
            )
        except Exception:
            log.exception("Alpaca snapshot failed for %s", symbol)
            return None
        snap = snaps.get(sym)
        if not snap:
            return None

        price = None
        if snap.latest_trade and snap.latest_trade.price:
            price = float(snap.latest_trade.price)
        elif snap.daily_bar and snap.daily_bar.close:
            price = float(snap.daily_bar.close)
        if not price:
            return None

        prev_close = float(snap.previous_daily_bar.close) if snap.previous_daily_bar else 0.0
        volume = float(snap.daily_bar.volume) if snap.daily_bar else 0.0
        avg_vol = await self._avg_daily_volume(sym)

        return {
            "price": price,
            "previousClose": prev_close,
            "volume": volume,
            "avgVolume": avg_vol,
        }

    async def _avg_daily_volume(self, symbol: str, days: int = 20) -> float:
        if not self._data:
            return 0.0
        end = datetime.now(timezone.utc)
        start = end - timedelta(days=days + 10)
        request = StockBarsRequest(
            symbol_or_symbols=symbol,
            timeframe=TimeFrame.Day,
            start=start,
            end=end,
            feed=self._feed,
        )
        try:
            response = await asyncio.to_thread(self._data.get_stock_bars, request)
        except Exception:
            return 0.0
        bars = response.data.get(symbol, [])
        vols = [float(b.volume) for b in bars[-days:] if b.volume]
        return sum(vols) / len(vols) if vols else 0.0

    async def place_bracket(
        self,
        symbol: str,
        direction: Direction,
        quantity: int,
        entry: float,
        stop: float,
        target: float,
    ) -> OrderPlacement:
        if not self._trading:
            raise RuntimeError("Alpaca not connected")

        if is_extended_hours():
            return await self._place_extended_entry(
                symbol, direction, quantity, entry, stop, target,
            )
        return await self._place_regular_bracket(
            symbol, direction, quantity, entry, stop, target,
        )

    async def _place_regular_bracket(
        self,
        symbol: str,
        direction: Direction,
        quantity: int,
        entry: float,
        stop: float,
        target: float,
    ) -> OrderPlacement:
        side = OrderSide.BUY if direction == Direction.LONG else OrderSide.SELL
        request = LimitOrderRequest(
            symbol=symbol.upper(),
            qty=quantity,
            side=side,
            time_in_force=TimeInForce.DAY,
            limit_price=round(entry, 2),
            order_class=OrderClass.BRACKET,
            take_profit=TakeProfitRequest(limit_price=round(target, 2)),
            stop_loss=StopLossRequest(stop_price=round(stop, 2)),
        )
        order = await asyncio.to_thread(self._trading.submit_order, request)
        log.info(
            "RTH bracket %s %s x%d entry=%.2f stop=%.2f target=%.2f id=%s",
            side.value, symbol, quantity, entry, stop, target, order.id,
        )
        return OrderPlacement(order_ids=[str(order.id)])

    async def _place_extended_entry(
        self,
        symbol: str,
        direction: Direction,
        quantity: int,
        entry: float,
        stop: float,
        target: float,
    ) -> OrderPlacement:
        """Extended hours: limit entry only; stop/target attached after fill."""
        side = OrderSide.BUY if direction == Direction.LONG else OrderSide.SELL
        request = LimitOrderRequest(
            symbol=symbol.upper(),
            qty=quantity,
            side=side,
            time_in_force=TimeInForce.DAY,
            limit_price=round(entry, 2),
            extended_hours=True,
        )
        order = await asyncio.to_thread(self._trading.submit_order, request)
        log.info(
            "Extended-hours entry %s %s x%d @ %.2f id=%s (stop/target on fill)",
            side.value, symbol, quantity, entry, order.id,
        )
        return OrderPlacement(order_ids=[str(order.id)], pending_exits=True)

    async def attach_exit_orders(
        self,
        symbol: str,
        direction: Direction,
        quantity: int,
        stop: float,
        target: float,
    ) -> list[str]:
        """OCO stop + take-profit after extended-hours entry fills."""
        if not self._trading:
            raise RuntimeError("Alpaca not connected")
        close_side = OrderSide.SELL if direction == Direction.LONG else OrderSide.BUY
        request = LimitOrderRequest(
            symbol=symbol.upper(),
            qty=quantity,
            side=close_side,
            time_in_force=TimeInForce.GTC,
            order_class=OrderClass.OCO,
            take_profit=TakeProfitRequest(limit_price=round(target, 2)),
            stop_loss=StopLossRequest(stop_price=round(stop, 2)),
        )
        order = await asyncio.to_thread(self._trading.submit_order, request)
        ids = [str(order.id)]
        if order.legs:
            ids.extend(str(leg.id) for leg in order.legs)
        log.info(
            "Exit OCO attached for %s stop=%.2f target=%.2f ids=%s",
            symbol, stop, target, ids,
        )
        return ids

    async def sync_pending_exits(self, trades: list[Trade]) -> None:
        if not self._trading:
            return
        for trade in trades:
            if not trade.pending_exits or not trade.order_ids:
                continue
            entry_id = trade.order_ids[0]
            try:
                order = await asyncio.to_thread(self._trading.get_order_by_id, entry_id)
            except Exception:
                log.exception("Failed to fetch order %s", entry_id)
                continue
            status = order.status
            if status == OrderStatus.FILLED:
                exit_ids = await self.attach_exit_orders(
                    trade.symbol, trade.direction, trade.quantity,
                    trade.stop, trade.target,
                )
                trade.order_ids.extend(exit_ids)
                trade.pending_exits = False
                log.info("Extended entry filled for %s — exits attached", trade.symbol)
            elif status in _TERMINAL - {OrderStatus.FILLED}:
                trade.pending_exits = False
                log.warning("Extended entry %s for %s ended as %s", entry_id, trade.symbol, status.value)

    async def close_position(self, symbol: str, direction: Direction, quantity: int) -> str:
        if not self._trading:
            raise RuntimeError("Alpaca not connected")
        close_side = OrderSide.SELL if direction == Direction.LONG else OrderSide.BUY
        sym = symbol.upper()

        if is_extended_hours():
            price = await self.last_price(symbol)
            if not price:
                raise RuntimeError(f"No quote for {symbol} — cannot close in extended hours")
            # Aggressive limit to cross the spread (extended hours: limit orders only).
            limit = round(price * 0.995, 2) if close_side == OrderSide.SELL else round(price * 1.005, 2)
            request = LimitOrderRequest(
                symbol=sym,
                qty=quantity,
                side=close_side,
                time_in_force=TimeInForce.DAY,
                limit_price=limit,
                extended_hours=True,
            )
        else:
            from alpaca.trading.requests import MarketOrderRequest
            request = MarketOrderRequest(
                symbol=sym,
                qty=quantity,
                side=close_side,
                time_in_force=TimeInForce.DAY,
            )
        order = await asyncio.to_thread(self._trading.submit_order, request)
        return str(order.id)

    async def list_open_orders(self) -> list[dict]:
        if not self._trading:
            return []
        try:
            orders = await asyncio.to_thread(
                self._trading.get_orders,
                filter=QueryOrderStatus.OPEN,
            )
        except Exception:
            log.exception("Failed to fetch open orders")
            return []
        out: list[dict] = []
        for o in orders:
            limit_px = getattr(o, "limit_price", None)
            stop_px = getattr(o, "stop_price", None)
            price = float(limit_px) if limit_px else (float(stop_px) if stop_px else None)
            out.append({
                "id": str(o.id),
                "symbol": o.symbol,
                "side": o.side.value if o.side else "",
                "qty": int(float(o.qty)) if o.qty else 0,
                "filled_qty": int(float(o.filled_qty)) if o.filled_qty else 0,
                "type": o.type.value if o.type else "",
                "status": o.status.value if o.status else "",
                "price": price,
                "order_class": o.order_class.value if o.order_class else "",
                "created_at": o.created_at.isoformat() if o.created_at else None,
            })
        out.sort(key=lambda r: r.get("created_at") or "", reverse=True)
        return out

    def cancel_orders(self, order_ids: list[str]) -> None:
        if not self._trading:
            return
        cancel_ids = {oid for oid in order_ids}
        open_orders = self._trading.get_orders(filter=QueryOrderStatus.OPEN)
        for order in open_orders:
            if str(order.id) in cancel_ids:
                try:
                    self._trading.cancel_order_by_id(order.id)
                except Exception:
                    log.exception("Failed to cancel Alpaca order %s", order.id)


def _to_bar(raw) -> Bar:
    ts = raw.timestamp
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return Bar(
        ts=ts,
        open=float(raw.open),
        high=float(raw.high),
        low=float(raw.low),
        close=float(raw.close),
        volume=float(raw.volume),
    )
