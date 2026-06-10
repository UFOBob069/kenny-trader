from datetime import datetime, timedelta, timezone

from app.models import Bar, Direction, SetupType
from app.signals.detector import SetupDetector

T0 = datetime(2026, 6, 10, 13, 30, tzinfo=timezone.utc)


def bar(i: int, o: float, h: float, l: float, c: float, v: float = 50_000) -> Bar:
    return Bar(ts=T0 + timedelta(minutes=i), open=o, high=h, low=l, close=c, volume=v)


def prior_day(price: float = 13.0, n: int = 100) -> list[Bar]:
    return [
        Bar(ts=T0 - timedelta(days=1) + timedelta(minutes=i),
            open=price, high=price + 0.05, low=price - 0.05, close=price, volume=20_000)
        for i in range(n)
    ]


def test_faux_show_bro_long():
    """Break the low, recover it, reclaim VWAP -> LONG signal."""
    det = SetupDetector("SOFI", prior_day_bars=prior_day(13.0))
    seq = [
        # establish a range around 14 (VWAP ~14)
        bar(0, 14.0, 14.1, 13.9, 14.0),
        bar(1, 14.0, 14.1, 13.9, 14.0),
        bar(2, 14.0, 14.2, 13.95, 14.1),
        bar(3, 14.1, 14.15, 13.9, 13.95),
        bar(4, 13.95, 14.0, 13.9, 13.95),
        bar(5, 13.95, 14.0, 13.9, 13.92),
        bar(6, 13.92, 13.95, 13.9, 13.91),
        # the foe: break the 13.9 low
        bar(7, 13.91, 13.92, 13.70, 13.75),
        # the show: recover above the broken low
        bar(8, 13.75, 13.95, 13.74, 13.93),
        # the breakout: reclaim VWAP
        bar(9, 13.93, 14.30, 13.92, 14.25),
    ]
    signals = []
    for b in seq:
        signals.extend(det.on_bar(b))

    assert len(signals) == 1
    sig = signals[0]
    assert sig.direction == Direction.LONG
    assert sig.setup == SetupType.FAUX_SHOW_BRO
    assert sig.stop == 13.70          # the fakeout low
    assert sig.entry == 14.25
    assert sig.target > sig.entry


def test_vwap_breakdown_short():
    """Extended above VWAP, then loses it -> SHORT targeting prior-day VWAP."""
    det = SetupDetector("SOFI", prior_day_bars=prior_day(12.0))
    seq = [bar(0, 14.0, 14.05, 13.95, 14.0)]
    # grind higher, well above vwap, for a while
    px = 14.0
    for i in range(1, 12):
        px += 0.06
        seq.append(bar(i, px, px + 0.05, px - 0.03, px + 0.03))
    # heavy break back through vwap
    seq.append(bar(12, px, px, 13.95, 14.0, v=500_000))

    signals = []
    for b in seq:
        signals.extend(det.on_bar(b))

    shorts = [s for s in signals if s.direction == Direction.SHORT]
    assert len(shorts) == 1
    sig = shorts[0]
    assert sig.setup == SetupType.VWAP_BREAKDOWN
    assert sig.stop > sig.entry        # stop at HOD
    assert sig.target < sig.entry      # target prior-day VWAP below


def test_no_signal_without_shakeout():
    """A plain VWAP cross with no prior fakeout should not fire the long."""
    det = SetupDetector("TSLA")
    seq = [
        bar(0, 10.0, 10.1, 9.9, 10.0),
        bar(1, 10.0, 10.1, 9.9, 9.95),
        bar(2, 9.95, 10.0, 9.9, 9.95),
        bar(3, 9.95, 10.0, 9.9, 9.95),
        bar(4, 9.95, 10.0, 9.9, 9.95),
        bar(5, 9.95, 10.0, 9.9, 9.95),
        bar(6, 9.95, 10.3, 9.94, 10.25),  # cross above vwap, but no fakeout happened
    ]
    signals = []
    for b in seq:
        signals.extend(det.on_bar(b))
    assert not [s for s in signals if s.setup == SetupType.FAUX_SHOW_BRO]
