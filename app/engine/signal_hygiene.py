"""Expire pending signals that are too old or no longer actionable."""
from __future__ import annotations

from datetime import datetime

from app.models import Direction, Signal


def expire_reason(
    sig: Signal,
    price: float | None,
    now: datetime,
    ttl_seconds: int,
    *,
    entry_slip_pct: float = 0.5,
) -> str | None:
    """Return a human-readable reason to expire, or None if still valid."""
    age = (now - sig.created_at).total_seconds()
    if age > ttl_seconds:
        return f"aged out ({ttl_seconds // 60} min)"

    if price is None or price <= 0:
        return None

    slip = entry_slip_pct / 100.0
    if sig.direction == Direction.LONG:
        if price <= sig.stop:
            return "stop breached"
        if price > sig.entry * (1 + slip):
            return "entry missed"
    else:
        if price >= sig.stop:
            return "stop breached"
        if price < sig.entry * (1 - slip):
            return "entry missed"
    return None
