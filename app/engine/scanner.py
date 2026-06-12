"""Candidate scanner: today's earnings + market movers -> filtered Candidates.

The daily *universe* is all earnings reporters and top movers. Symbols are
watched on the chart immediately. *Candidates* are the subset that also pass
gap / relative-volume filters (used for signal emphasis).
"""
from __future__ import annotations

import logging

from app.config import settings
from app.data.scan_data import DailyScanData
from app.engine.scoring import criteria_score
from app.models import Candidate, WatchItem

log = logging.getLogger(__name__)


class Scanner:
    def __init__(self, scan_data: DailyScanData, watchlist: set[str] | None = None) -> None:
        self.scan_data = scan_data
        self.watchlist: set[str] = watchlist or set()

    async def universe(self) -> dict[str, str]:
        """Raw daily scan list: symbol -> catalyst (earnings | mover | news)."""
        symbols = await self.scan_data.daily_symbols()
        for sym in self.watchlist:
            symbols.setdefault(sym.upper(), "news")
        return symbols

    def rank_universe(self, symbols: dict[str, str]) -> list[str]:
        """Earnings names first, then movers, then watchlist."""
        earnings = sorted(s for s, c in symbols.items() if c == "earnings")
        movers = sorted(s for s, c in symbols.items() if c == "mover")
        other = sorted(s for s, c in symbols.items() if c not in ("earnings", "mover"))
        return earnings + movers + other

    async def scan(self) -> list[Candidate]:
        symbols = await self.universe()
        log.info("Scanning %d symbols from daily universe", len(symbols))
        candidates: list[Candidate] = []
        for sym, catalyst in symbols.items():
            cand = await self._evaluate(sym, catalyst, require_filters=True)
            if cand:
                candidates.append(cand)

        candidates.sort(key=lambda c: abs(c.gap_pct) * max(c.relative_volume, 1), reverse=True)
        log.info("Filtered candidates: %s", [c.symbol for c in candidates])
        return candidates

    async def snapshot(self, symbol: str, catalyst: str) -> Candidate | None:
        """Build candidate metadata without gap/rvol filters (for chart watching)."""
        return await self._evaluate(symbol, catalyst, require_filters=False, with_news=False)

    async def watch_entry(self, symbol: str, catalyst: str, *, with_news: bool = False) -> WatchItem:
        """Scored row for the dashboard watchlist."""
        sym = symbol.upper()
        quote = await self.scan_data.quote(sym)
        if not quote:
            return WatchItem(symbol=sym, catalyst=catalyst)

        price = float(quote.get("price") or 0)
        prior_close = float(quote.get("previousClose") or 0)
        avg_vol = float(quote.get("avgVolume") or 0)
        volume = float(quote.get("volume") or 0)
        gap_pct = (price - prior_close) / prior_close * 100 if prior_close else 0.0
        rvol = volume / avg_vol if avg_vol else 0.0
        score, qualified, checks = criteria_score(gap_pct, rvol, price, catalyst)

        earnings = await self.scan_data.earnings_for(sym, catalyst) if with_news else None
        headlines = await self.scan_data.headlines(sym) if with_news else []

        return WatchItem(
            symbol=sym,
            catalyst=catalyst,
            price=round(price, 2),
            gap_pct=round(gap_pct, 2),
            relative_volume=round(rvol, 2),
            score=score,
            qualified=qualified,
            checks=checks,
            earnings=earnings,
            headlines=headlines,
        )

    async def _evaluate(
        self,
        symbol: str,
        catalyst: str,
        *,
        require_filters: bool,
        with_news: bool = True,
    ) -> Candidate | None:
        quote = await self.scan_data.quote(symbol)
        if not quote:
            return None

        price = quote.get("price") or 0
        prior_close = quote.get("previousClose") or 0
        avg_vol = quote.get("avgVolume") or 0
        volume = quote.get("volume") or 0

        if prior_close <= 0:
            return None

        gap_pct = (price - prior_close) / prior_close * 100
        rvol = volume / avg_vol if avg_vol else 0.0

        if require_filters:
            _, qualified, _ = criteria_score(gap_pct, rvol, price, catalyst)
            if not qualified:
                return None

        earnings = await self.scan_data.earnings_for(symbol, catalyst) if with_news else None
        headlines = await self.scan_data.headlines(symbol) if with_news else []

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
