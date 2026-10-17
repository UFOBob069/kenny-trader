"""Daily scan universe: Finnhub earnings today + Alpaca top movers."""
from __future__ import annotations

import asyncio
import logging
from time import monotonic
from typing import TYPE_CHECKING

from app.config import settings
from app.data.finnhub import FinnhubClient, normalize_earnings
from app.data.symbol_filter import is_common_ticker

if TYPE_CHECKING:
    from app.data.alpaca import AlpacaClient
    from app.engine.risk import RuntimeRules

log = logging.getLogger(__name__)


class DailyScanData:
    def __init__(
        self,
        finnhub: FinnhubClient,
        alpaca: AlpacaClient | None = None,
        rules: RuntimeRules | None = None,
    ) -> None:
        self.finnhub = finnhub
        self.alpaca = alpaca
        self.rules = rules
        self._earnings_rows: dict[str, dict] = {}
        self._cap_cache: dict[str, float | None] = {}
        self._russell: set[str] | None = None
        self._quote_cache: dict[str, tuple[float, dict]] = {}
        self.filter_errors: list[str] = []
        self.source_errors: list[str] = []
        self.raw_symbol_count = 0

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

        filtered = await self._apply_universe_filters(symbols)
        self.raw_symbol_count = len(symbols)
        self.source_errors = list(getattr(self.finnhub, 'errors', {}).values())
        if self.alpaca:
            self.source_errors.extend(getattr(self.alpaca, 'scan_errors', {}).values())
        self._earnings_rows = {k: v for k, v in self._earnings_rows.items() if k in filtered}
        log.info(
            "Daily scan list: %d earnings today, %d after universe filter",
            len(self._earnings_rows),
            len(filtered),
        )
        return filtered

    async def _apply_universe_filters(self, symbols: dict[str, str]) -> dict[str, str]:
        """NYSE/Nasdaq common stocks in Russell 1000 only."""
        self.filter_errors = []
        if not symbols:
            return {}

        russell: set[str] | None = None
        russell_on = self.rules.scan_russell_1000_only if self.rules else True
        if russell_on:
            russell = await self.finnhub.russell_1000_symbols()
            self._russell = russell or None
            if not russell:
                self.filter_errors.append("Russell 1000 membership unavailable; scan paused while this filter is enabled.")
                detail = getattr(self.finnhub, 'membership_status', {}).get('error')
                if detail:
                    self.filter_errors.append(detail)
                log.warning(self.filter_errors[-1])
                return {}

        exchange_ok: set[str] | None = None
        if self.alpaca:
            exchange_ok = await self.alpaca.nyse_nasdaq_symbols()
            if not exchange_ok:
                self.filter_errors.append("NYSE/Nasdaq asset list unavailable; scan paused.")
                log.warning(self.filter_errors[-1])
                return {}

        kept: dict[str, str] = {}
        dropped = 0
        for sym, catalyst in symbols.items():
            sym = sym.upper()
            if not is_common_ticker(sym):
                dropped += 1
                continue
            if russell is not None and len(russell) > 0 and sym not in russell:
                dropped += 1
                continue
            if exchange_ok is not None and len(exchange_ok) > 0 and sym not in exchange_ok:
                dropped += 1
                continue
            kept[sym] = catalyst

        log.info(
            "Universe filter (%s): %d kept, %d dropped",
            "Russell 1000 + NYSE/Nasdaq" if russell_on else "NYSE/Nasdaq",
            len(kept),
            dropped,
        )
        return kept

    async def quote(self, symbol: str) -> dict | None:
        if not self.alpaca:
            return None
        cached = self._quote_cache.get(symbol)
        if cached and monotonic() - cached[0] < min(5, settings.max_quote_age_seconds):
            return self._quote_metrics(symbol, cached[1])
        quote = await self.alpaca.quote_snapshot(symbol)
        if quote:
            self._quote_cache[symbol] = (monotonic(), quote)
        return self._quote_metrics(symbol, quote) if quote else None

    def _quote_metrics(self, symbol: str, quote: dict) -> dict:
        return {
            **quote, "relativeVolume": self.alpaca.relative_volume(symbol),
            "liquidity": {**self.alpaca.liquidity_activity(symbol),
                          **{key: quote.get(key) for key in ("bid", "ask", "quote_at")}},
        }

    async def market_cap(self, symbol: str, price: float | None = None) -> float | None:
        sym = symbol.upper()
        if sym not in self._cap_cache or self._cap_cache[sym] is None:
            px = price
            if px is None and self.alpaca:
                quote = await self.quote(sym)
                px = float(quote["price"]) if quote and quote.get("price") else None
            self._cap_cache[sym] = await self.finnhub.market_cap_usd(sym, price=px)
        return self._cap_cache[sym]

    async def filter_by_market_cap(self, symbols: dict[str, str], floor_usd: float) -> dict[str, str]:
        """Drop symbols below floor_usd (Finnhub). floor_usd=0 disables."""
        if floor_usd <= 0:
            return symbols
        kept: dict[str, str] = {}
        dropped = 0
        semaphore = asyncio.Semaphore(4)

        async def lookup(sym):
            async with semaphore:
                return await self.market_cap(sym)

        caps = await asyncio.gather(*(lookup(sym) for sym in symbols))
        for (sym, catalyst), cap in zip(symbols.items(), caps):
            if cap is not None and cap >= floor_usd:
                kept[sym] = catalyst
            else:
                dropped += 1
                if cap is None:
                    self.filter_errors.append(f"{sym}: market cap unavailable; excluded by the enabled cap filter.")
        log.info(
            "Market cap filter (>= $%.0fM): %d kept, %d dropped",
            floor_usd / 1_000_000,
            len(kept),
            dropped,
        )
        return kept

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
