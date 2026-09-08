"""Observed spread and recent turnover checks, not a fill guarantee."""
import math
from datetime import datetime, timedelta

from app.config import settings
from app.data.bar_sessions import completed_bars
from app.models import Bar


def recent_activity(bars: list[Bar], now: datetime) -> dict:
    end = now.replace(second=0, microsecond=0)
    start = end - timedelta(minutes=5)
    recent = [b for b in completed_bars(bars, now) if start <= b.ts < end]
    valid = [b for b in recent if math.isfinite(b.volume) and b.volume > 0
             and math.isfinite(b.close) and b.close > 0]
    return {
        "dollar_volume_5m": sum(b.close * b.volume for b in valid),
        "shares_per_minute": sum(b.volume for b in valid) / 5,
        "active_minutes": len(valid),
        "activity_at": end,
    }


def liquidity_checks(data: dict | None, now: datetime) -> dict:
    data = data or {}
    bid, ask = data.get("bid"), data.get("ask")
    valid_book = all(isinstance(p, (int, float)) and math.isfinite(p) and p > 0 for p in (bid, ask))
    valid_book = valid_book and ask >= bid
    spread_pct = (ask - bid) / ((ask + bid) / 2) * 100 if valid_book else None
    quote_at = data.get("quote_at")
    activity_at = data.get("activity_at")

    def fresh(ts, seconds):
        return isinstance(ts, datetime) and ts.tzinfo is not None and 0 <= (now - ts).total_seconds() <= seconds

    dollar_volume = data.get("dollar_volume_5m", 0)
    active = data.get("active_minutes", 0)
    return {
        "dollar_volume": {"ok": fresh(activity_at, 90) and math.isfinite(dollar_volume)
                          and dollar_volume >= settings.min_dollar_volume_5m,
                          "value": round(dollar_volume, 2), "need": settings.min_dollar_volume_5m},
        "spread": {"ok": valid_book and fresh(quote_at, settings.max_quote_age_seconds)
                   and spread_pct <= settings.max_spread_pct,
                   "value": round(spread_pct, 3) if spread_pct is not None else None,
                   "need": settings.max_spread_pct},
        "activity": {"ok": fresh(activity_at, 90) and active >= settings.min_active_minutes,
                     "value": active, "need": settings.min_active_minutes},
    }


def execution_liquidity_reason(data: dict, now: datetime, quantity: int, risk_per_share: float) -> str | None:
    checks = liquidity_checks(data, now)
    for name, check in checks.items():
        if not check["ok"]:
            return f"liquidity check failed: {name} (missing, stale, or outside limit)"
    capacity = data.get("shares_per_minute", 0) * settings.max_volume_participation_pct / 100
    if not math.isfinite(capacity) or quantity <= 0 or quantity > capacity:
        return "order too large for recent traded volume"
    if risk_per_share <= 0 or (data["ask"] - data["bid"]) > risk_per_share * settings.max_spread_risk_pct / 100:
        return "spread too large relative to stop distance"
    return None
