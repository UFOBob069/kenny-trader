"""Finnhub client: today's earnings calendar, news, EPS history."""
from __future__ import annotations

import logging
from datetime import timedelta

import httpx

from app.config import settings
from app.data.market_hours import ET, trading_date
from app.data.symbol_filter import is_common_ticker

log = logging.getLogger(__name__)
BASE = "https://finnhub.io/api/v1"
_RUSSELL_CACHE: set[str] | None = None
_RUSSELL_CACHE_DATE = None


def market_cap_from_profile(profile: dict, price: float | None = None) -> float | None:
    """Finnhub profile2: marketCapitalization and shareOutstanding are in millions."""
    mcap = profile.get("marketCapitalization")
    if mcap is not None:
        return float(mcap) * 1_000_000
    shares_m = profile.get("shareOutstanding")
    if shares_m is not None and price and price > 0:
        return float(shares_m) * 1_000_000 * price
    return None


def normalize_earnings(row: dict) -> dict:
    """Map Finnhub fields to the shape used by the confidence engine."""
    return {
        "actualEarningResult": row.get("epsActual") if row.get("epsActual") is not None else row.get("actual"),
        "estimatedEarning": row.get("epsEstimate") if row.get("epsEstimate") is not None else row.get("estimate"),
        "revenue": row.get("revenueActual") if row.get("revenueActual") is not None else row.get("revenue"),
        "revenueEstimated": row.get("revenueEstimate"),
    }


class FinnhubClient:
    def __init__(self) -> None:
        self._http = httpx.AsyncClient(timeout=20)

    async def close(self) -> None:
        await self._http.aclose()

    async def _get(self, path: str, **params) -> dict | list:
        if not settings.finnhub_api_key:
            return {}
        params["token"] = settings.finnhub_api_key
        try:
            r = await self._http.get(f"{BASE}{path}", params=params)
            r.raise_for_status()
            return r.json()
        except Exception:
            log.exception("Finnhub request failed: %s", path)
            return {}

    async def earnings_today(self) -> list[dict]:
        """US symbols reporting earnings on today's US market date (ET)."""
        if not settings.finnhub_api_key:
            log.warning("FINNHUB_API_KEY not set — earnings calendar will be empty")
            return []
        today = trading_date().isoformat()
        data = await self._get("/calendar/earnings", **{"from": today, "to": today})
        rows = data.get("earningsCalendar", []) if isinstance(data, dict) else []
        return [r for r in rows if r.get("symbol") and is_common_ticker(r["symbol"])]

    async def russell_1000_symbols(self) -> set[str]:
        """Russell 1000 proxy: holdings of the IWB ETF (refreshed daily)."""
        global _RUSSELL_CACHE, _RUSSELL_CACHE_DATE
        today = trading_date()
        if _RUSSELL_CACHE is not None and _RUSSELL_CACHE_DATE == today:
            return _RUSSELL_CACHE

        symbols: set[str] = set()
        skip = 0
        while True:
            data = await self._get("/etf/holdings", symbol="IWB", skip=skip)
            if not isinstance(data, dict):
                break
            holdings = data.get("holdings") or []
            if not holdings:
                break
            for row in holdings:
                sym = row.get("symbol") or row.get("ticker")
                if sym and is_common_ticker(sym):
                    symbols.add(sym.upper())
            if len(holdings) < 100:
                break
            skip += len(holdings)

        if symbols:
            _RUSSELL_CACHE = symbols
            _RUSSELL_CACHE_DATE = today
            log.info("Russell 1000 universe loaded: %d symbols (IWB holdings)", len(symbols))
        else:
            log.warning("Russell 1000 load failed — scanner will use exchange filter only")
        return symbols

    async def earnings_history(self, symbol: str) -> dict | None:
        """Most recent reported quarter (for EPS beat/miss after release)."""
        rows = await self._get("/stock/earnings", symbol=symbol.upper())
        if not isinstance(rows, list) or not rows:
            return None
        return normalize_earnings(rows[0])

    async def market_cap_usd(self, symbol: str, price: float | None = None) -> float | None:
        if not settings.finnhub_api_key:
            return None
        data = await self._get("/stock/profile2", symbol=symbol.upper())
        if not isinstance(data, dict) or not data:
            return None
        # profile2 uses "ticker", not "symbol"
        if not (data.get("ticker") or data.get("symbol") or data.get("marketCapitalization")):
            return None
        return market_cap_from_profile(data, price=price)

    async def company_news(self, symbol: str, days: int = 7) -> list[str]:
        from datetime import datetime

        end = datetime.now(ET).date()
        start = end - timedelta(days=days)
        rows = await self._get(
            "/company-news",
            symbol=symbol.upper(),
            **{"from": start.isoformat(), "to": end.isoformat()},
        )
        if not isinstance(rows, list):
            return []
        rows.sort(key=lambda r: r.get("datetime", 0), reverse=True)
        return [f"{r.get('headline', '')} — {(r.get('summary') or '')[:200]}" for r in rows[:8]]
