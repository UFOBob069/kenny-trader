from datetime import date, datetime, timezone
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest

from app.data.market_hours import is_extended_hours, is_morning_setup_window, market_session, trading_date

ET = ZoneInfo("America/New_York")


def _et(y, m, d, h, mi=0):
    return datetime(y, m, d, h, mi, tzinfo=ET)


def test_pre_market():
    assert market_session(_et(2026, 6, 10, 7, 0)) == "pre"
    assert is_extended_hours(_et(2026, 6, 10, 7, 0))


def test_regular_hours():
    assert market_session(_et(2026, 6, 10, 10, 0)) == "regular"
    assert not is_extended_hours(_et(2026, 6, 10, 10, 0))


def test_post_market():
    assert market_session(_et(2026, 6, 10, 17, 0)) == "post"
    assert is_extended_hours(_et(2026, 6, 10, 17, 0))


def test_closed_weekend():
    assert market_session(_et(2026, 6, 13, 10, 0)) == "closed"


def test_trading_date_uses_et():
    # 02:00 UTC on Friday is still Thursday evening in New York
    fixed = datetime(2026, 6, 12, 2, 0, tzinfo=timezone.utc)
    with patch("app.data.market_hours.datetime") as m:
        m.now.side_effect = lambda tz=None: fixed.astimezone(tz) if tz else fixed
        assert trading_date() == date(2026, 6, 11)


@pytest.mark.parametrize("hour,minute,allowed", [
    (8, 29, False), (8, 30, True), (9, 14, True), (9, 15, False),
    (9, 30, False), (9, 35, True), (11, 29, True), (11, 30, False), (14, 0, False),
])
def test_morning_entry_windows(hour, minute, allowed):
    assert is_morning_setup_window(_et(2026, 9, 8, hour, minute)) is allowed
