"""Finnhub client: today's earnings calendar, news, EPS history."""
from __future__ import annotations

import logging
from datetime import timedelta

import httpx

from app.config import settings
from app.data.market_hours import ET, trading_date
from app.data.symbol_filter import is_common_ticker
from app.data.iwb_holdings import IwbHoldings

log = logging.getLogger(__name__)
BASE = "https://finnhub.io/api/v1"


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
        self._membership = IwbHoldings(self._http)
        self.errors: dict[str, str] = {}

    @property
    def membership_status(self) -> dict:
        return dict(self._membership.status)

    async def close(self) -> None:
        await self._http.aclose()

    async def _get(self, path: str, **params) -> dict | list:
        if not settings.finnhub_api_key:
            self.errors[path] = 'Finnhub credentials not configured'
            return {}
        params["token"] = settings.finnhub_api_key
        try:
            r = await self._http.get(f"{BASE}{path}", params=params)
            r.raise_for_status()
            data = r.json()
            self.errors.pop(path, None)
            return data
        except (httpx.HTTPError, ValueError) as exc:
            code = exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else None
            error = {401: 'credentials rejected', 403: 'subscription access denied',
                     429: 'rate limit reached'}.get(code, f'HTTP {code}' if code else 'provider unavailable or invalid response')
            self.errors[path] = f'Finnhub {error}'
            # httpx exception strings may include the secret token query parameter.
            log.warning("Finnhub request failed: %s (%s)", path, error)
            return {}

    async def earnings_today(self) -> list[dict]:
        """US symbols reporting earnings on today's US market date (ET)."""
        if not settings.finnhub_api_key:
            self.errors['/calendar/earnings'] = 'Finnhub earnings credentials not configured'
            log.warning("FINNHUB_API_KEY not set — earnings calendar will be empty")
            return []
        today = trading_date().isoformat()
        data = await self._get("/calendar/earnings", **{"from": today, "to": today})
        rows = data.get("earningsCalendar", []) if isinstance(data, dict) else []
        return [r for r in rows if r.get("symbol") and is_common_ticker(r["symbol"])]

    async def russell_1000_symbols(self) -> set[str]:
        """Same IWB proxy, obtained from its issuer without a Finnhub ETF entitlement."""
        return await self._membership.symbols()

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
