"""US equity session helpers (Eastern Time)."""
from __future__ import annotations

from datetime import datetime, time, timezone
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")

PRE_OPEN = time(4, 0)
RTH_OPEN = time(9, 30)
RTH_CLOSE = time(16, 0)
POST_CLOSE = time(20, 0)


def market_session(now: datetime | None = None) -> str:
    """Return pre | regular | post | closed."""
    now = (now or datetime.now(timezone.utc)).astimezone(ET)
    if now.weekday() >= 5:
        return "closed"
    t = now.time()
    if PRE_OPEN <= t < RTH_OPEN:
        return "pre"
    if RTH_OPEN <= t < RTH_CLOSE:
        return "regular"
    if RTH_CLOSE <= t < POST_CLOSE:
        return "post"
    return "closed"


def is_extended_hours(now: datetime | None = None) -> bool:
    return market_session(now) in ("pre", "post")


def is_regular_hours(now: datetime | None = None) -> bool:
    return market_session(now) == "regular"
