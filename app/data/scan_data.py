"""Daily scan universe: Finnhub earnings today + Alpaca top movers."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from app.config import settings
from app.data.finnhub import FinnhubClient, normalize_earnings

if TYPE_CHECKING:
    from app.data.alpaca import AlpacaClient

log = logging.getLogger(__name__)


class DailyScanData:
    def __init__(self, finnhub: FinnhubClient, alpaca: AlpacaClient | None = None) -> None:
        self.finnhub = finnhub
        self.alpaca = alpaca
        self._earnings_rows: dict[str, dict] = {}

    async def close(self) -> None:
        await self.finnhub.close()

    async def daily_symbols(self) -> dict[str, str]:
        """symbol -> catalyst: earnings | mover | news (watchlist)."""
        symbols: dict[str, str] = {}
        self._earnings_rows = {}

        for row in await self.finnhub.earnings_today():
            sym = row["symbol"].upper()
            self._earnings_rows[sym] = row
            symbols[sym] = "earnings"

        if self.alpaca:
            for sym in await self.alpaca.market_movers(top=settings.alpaca_movers_top):
                symbols.setdefault(sym.upper(), "mover")

        log.info(
            "Daily scan list: %d earnings today, %d total symbols",
            len(self._earnings_rows),
            len(symbols),
        )
        return symbols

    async def quote(self, symbol: str) -> dict | None:
        if not self.alpaca:
            return None
        return await self.alpaca.quote_snapshot(symbol)

    async def earnings_for(self, symbol: str, catalyst: str) -> dict | None:
        if catalyst != "earnings":
            return None
        sym = symbol.upper()
        row = self._earnings_rows.get(sym)
        if row:
            merged = normalize_earnings(row)
            if merged.get("actualEarningResult") is not None:
                return merged
        return await self.finnhub.earnings_history(sym)

    async def headlines(self, symbol: str) -> list[str]:
        return await self.finnhub.company_news(symbol)
