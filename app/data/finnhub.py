"""Finnhub client: today's earnings calendar, news, EPS history."""
from __future__ import annotations

import logging
from datetime import timedelta

import httpx

from app.config import settings
from app.data.market_hours import ET, trading_date

log = logging.getLogger(__name__)
BASE = "https://finnhub.io/api/v1"


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
        return [r for r in rows if r.get("symbol") and "." not in r["symbol"]]

    async def earnings_history(self, symbol: str) -> dict | None:
        """Most recent reported quarter (for EPS beat/miss after release)."""
        rows = await self._get("/stock/earnings", symbol=symbol.upper())
        if not isinstance(rows, list) or not rows:
            return None
        return normalize_earnings(rows[0])

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
