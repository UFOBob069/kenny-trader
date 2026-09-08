from datetime import datetime, timedelta, timezone

import pytest

from app.engine.liquidity import execution_liquidity_reason, liquidity_checks, recent_activity
from app.models import Bar

NOW = datetime(2026, 9, 8, 14, 10, 5, tzinfo=timezone.utc)


def liquid():
    return {"bid": 1.5, "ask": 1.51, "quote_at": NOW,
            "activity_at": NOW.replace(second=0), "dollar_volume_5m": 1_000_000,
            "shares_per_minute": 100_000, "active_minutes": 5}


def test_recent_activity_uses_wall_clock_window_and_zero_volume_for_missing_minutes():
    bars = [Bar(ts=NOW.replace(second=0) - timedelta(minutes=i), open=10, high=10, low=10,
                close=10, volume=1000) for i in (0, 1, 3, 6)]
    metrics = recent_activity(bars + [bars[1]], NOW)
    assert metrics["dollar_volume_5m"] == 20_000
    assert metrics["shares_per_minute"] == 400
    assert metrics["active_minutes"] == 2


@pytest.mark.parametrize("patch,failed", [
    ({"bid": None}, "spread"), ({"bid": 2}, "spread"),
    ({"ask": 1.6}, "spread"), ({"bid": float('nan')}, "spread"),
    ({"quote_at": NOW - timedelta(seconds=16)}, "spread"),
    ({"quote_at": NOW + timedelta(seconds=1)}, "spread"),
    ({"activity_at": NOW - timedelta(minutes=5)}, "activity"),
    ({"active_minutes": 1}, "activity"), ({"dollar_volume_5m": 1000}, "dollar_volume"),
])
def test_rejects_missing_stale_or_thin_liquidity(patch, failed):
    assert not liquidity_checks({**liquid(), **patch}, NOW)[failed]["ok"]


def test_order_capacity_uses_actual_planned_shares():
    assert execution_liquidity_reason(liquid(), NOW, 500, .1) is None
    assert execution_liquidity_reason(liquid(), NOW, 1001, .1) == "order too large for recent traded volume"


def test_small_percentage_spread_can_still_consume_too_much_trade_risk():
    assert execution_liquidity_reason(liquid(), NOW, 500, .02) == "spread too large relative to stop distance"
