from datetime import datetime, timedelta, timezone

from app.data.bar_sessions import completed_bars, split_sessions
from app.models import Bar


def bar(ts):
    return Bar(ts=ts, open=10, high=11, low=9, close=10, volume=100)


def test_completed_bars_sorted_deduplicated_and_no_partial_candle():
    now = datetime(2026, 9, 8, 14, 0, 30, tzinfo=timezone.utc)
    old = bar(now.replace(minute=59, hour=13, second=0))
    current = bar(now.replace(second=0))
    assert completed_bars([current, old, old], now) == [old]


def test_prior_vwap_uses_one_session_across_holiday_weekend():
    now = datetime(2026, 9, 8, 14, tzinfo=timezone.utc)
    thursday = bar(now - timedelta(days=5, hours=1))
    friday = bar(now - timedelta(days=4, hours=1))
    today = bar(now - timedelta(minutes=1))
    assert split_sessions([thursday, friday, today], now) == ([friday], [today])


def test_closed_day_does_not_relabel_friday_as_today():
    now = datetime(2026, 9, 7, 14, tzinfo=timezone.utc)
    friday = bar(now - timedelta(days=3))
    assert split_sessions([friday], now) == ([friday], [])


def test_extended_session_is_split_by_eastern_date_not_utc():
    now = datetime(2026, 1, 7, 14, tzinfo=timezone.utc)
    prior_evening = bar(datetime(2026, 1, 7, 0, 30, tzinfo=timezone.utc))
    today = bar(now - timedelta(minutes=1))
    assert split_sessions([prior_evening, today], now) == ([prior_evening], [today])
