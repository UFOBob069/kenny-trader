"""Candidate scanner: earnings reporters + watchlist -> filtered Candidates.

Filters (configurable): |gap| >= min_gap_pct, relative volume >= min,
price >= min_price, and a catalyst must exist.
"""
from __future__ import annotations

import logging

from app.config import settings
from app.data.fmp import FmpClient
from app.models import Candidate

log = logging.getLogger(__name__)


class Scanner:
    def __init__(self, fmp: FmpClient, watchlist: set[str] | None = None) -> None:
        self.fmp = fmp
        self.watchlist: set[str] = watchlist or set()

    async def scan(self) -> list[Candidate]:
        symbols: dict[str, str] = {}  # symbol -> catalyst

        for row in await self.fmp.earnings_calendar():
            sym = row.get("symbol", "")
            # skip foreign listings with exchange suffixes
            if sym and "." not in sym:
                symbols[sym] = "earnings"

        for sym in self.watchlist:
            symbols.setdefault(sym.upper(), "news")

        log.info("Scanning %d symbols", len(symbols))
        candidates: list[Candidate] = []
        for sym, catalyst in symbols.items():
            cand = await self._evaluate(sym, catalyst)
            if cand:
                candidates.append(cand)

        candidates.sort(key=lambda c: abs(c.gap_pct) * max(c.relative_volume, 1), reverse=True)
        log.info("Candidates: %s", [c.symbol for c in candidates])
        return candidates

    async def _evaluate(self, symbol: str, catalyst: str) -> Candidate | None:
        quote = await self.fmp.quote(symbol)
        if not quote:
            return None

        price = quote.get("price") or 0
        prior_close = quote.get("previousClose") or 0
        avg_vol = quote.get("avgVolume") or 0
        volume = quote.get("volume") or 0

        if price < settings.min_price or prior_close <= 0:
            return None

        gap_pct = (price - prior_close) / prior_close * 100
        rvol = volume / avg_vol if avg_vol else 0.0

        # watchlist names only need to clear price; earnings names need gap + volume
        if catalyst == "earnings":
            if abs(gap_pct) < settings.min_gap_pct or rvol < settings.min_relative_volume:
                return None

        earnings = await self.fmp.earnings_surprise(symbol) if catalyst == "earnings" else None
        headlines = await self.fmp.stock_news(symbol)

        return Candidate(
            symbol=symbol,
            gap_pct=round(gap_pct, 2),
            relative_volume=round(rvol, 2),
            price=price,
            prior_close=prior_close,
            avg_volume=avg_vol,
            catalyst=catalyst,
            earnings=earnings,
            headlines=headlines,
        )
