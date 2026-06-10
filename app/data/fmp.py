"""Financial Modeling Prep client: earnings calendar, surprises, news."""
from __future__ import annotations

import logging
from datetime import date, timedelta

import httpx

from app.config import settings

log = logging.getLogger(__name__)
BASE = "https://financialmodelingprep.com/api/v3"


class FmpClient:
    def __init__(self) -> None:
        self._http = httpx.AsyncClient(timeout=20)

    async def close(self) -> None:
        await self._http.aclose()

    async def _get(self, path: str, **params) -> list | dict:
        if not settings.fmp_api_key:
            return []
        params["apikey"] = settings.fmp_api_key
        try:
            r = await self._http.get(f"{BASE}/{path}", params=params)
            r.raise_for_status()
            return r.json()
        except Exception:
            log.exception("FMP request failed: %s", path)
            return []

    async def earnings_calendar(self) -> list[dict]:
        """Earnings from yesterday (after-close reporters) through today (pre-open)."""
        today = date.today()
        rows = await self._get(
            "earning_calendar",
            **{"from": (today - timedelta(days=1)).isoformat(), "to": today.isoformat()},
        )
        return rows if isinstance(rows, list) else []

    async def earnings_surprise(self, symbol: str) -> dict | None:
        rows = await self._get(f"earnings-surprises/{symbol}")
        return rows[0] if isinstance(rows, list) and rows else None

    async def stock_news(self, symbol: str, limit: int = 8) -> list[str]:
        rows = await self._get("stock_news", tickers=symbol, limit=limit)
        if not isinstance(rows, list):
            return []
        return [f"{r.get('title', '')} — {r.get('text', '')[:200]}" for r in rows]

    async def profile(self, symbol: str) -> dict | None:
        rows = await self._get(f"profile/{symbol}")
        return rows[0] if isinstance(rows, list) and rows else None

    async def quote(self, symbol: str) -> dict | None:
        rows = await self._get(f"quote/{symbol}")
        return rows[0] if isinstance(rows, list) and rows else None
