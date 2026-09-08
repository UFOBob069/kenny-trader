from datetime import datetime, timedelta, timezone

from app.data.relative_volume import RelativeVolumeProfile
from app.models import Bar


NOW = datetime(2026, 9, 10, 13, 32, tzinfo=timezone.utc)


def bar(ts, volume):
    return Bar(ts=ts, open=10, high=11, low=9, close=10, volume=volume)


def history():
    result = []
    for days in (1, 2, 6):
        start = NOW - timedelta(days=days, minutes=2)
        result.extend([bar(start, 100), bar(start + timedelta(minutes=1), 100),
                       bar(start + timedelta(hours=4), 10000)])
    return result


def test_morning_rvol_compares_same_time_not_full_day():
    profile = RelativeVolumeProfile(history(), NOW)
    today = [bar(NOW - timedelta(minutes=2), 300), bar(NOW - timedelta(minutes=1), 300)]
    value, ts = profile.measure(today, NOW)
    assert value == 3
    assert ts == today[-1].ts


def test_insufficient_history_is_unknown_not_daily_volume_fallback():
    profile = RelativeVolumeProfile(history()[:3], NOW)
    assert profile.measure([bar(NOW - timedelta(minutes=1), 1000)], NOW) == (None, None)


def test_profile_rejects_next_day_and_partial_bars():
    profile = RelativeVolumeProfile(history(), NOW)
    assert profile.measure([bar(NOW, 10000)], NOW) == (None, None)
    tomorrow = NOW + timedelta(days=1)
    assert profile.measure([bar(tomorrow - timedelta(minutes=1), 1000)], tomorrow) == (None, None)
