from datetime import datetime, timedelta, timezone

from app.engine.signal_hygiene import expire_reason
from app.models import Direction, SetupType, Signal


def _sig(direction: Direction, entry: float, stop: float, age_sec: int = 0) -> Signal:
    return Signal(
        symbol="TEST",
        direction=direction,
        setup=SetupType.FAUX_SHOW_BRO,
        entry=entry,
        stop=stop,
        target=entry + 2 * abs(entry - stop),
        created_at=datetime.now(timezone.utc) - timedelta(seconds=age_sec),
    )


def test_expire_on_age():
    sig = _sig(Direction.LONG, 10.0, 9.0, age_sec=700)
    now = datetime.now(timezone.utc)
    assert expire_reason(sig, 10.0, now, 600) == "aged out (10 min)"


def test_expire_long_stop_breached():
    sig = _sig(Direction.LONG, 10.0, 9.0)
    now = datetime.now(timezone.utc)
    assert expire_reason(sig, 8.9, now, 600) == "stop breached"


def test_expire_long_entry_missed():
    sig = _sig(Direction.LONG, 10.0, 9.0)
    now = datetime.now(timezone.utc)
    assert expire_reason(sig, 10.06, now, 600) == "entry missed"


def test_expire_short_stop_breached():
    sig = _sig(Direction.SHORT, 10.0, 11.0)
    now = datetime.now(timezone.utc)
    assert expire_reason(sig, 11.1, now, 600) == "stop breached"


def test_still_valid_near_entry():
    sig = _sig(Direction.LONG, 10.0, 9.0)
    now = datetime.now(timezone.utc)
    assert expire_reason(sig, 10.02, now, 600) is None
