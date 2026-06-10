from datetime import datetime, timedelta, timezone

from app.models import Bar
from app.signals.vwap import VwapTracker, running_vwap


def make_bar(i: int, price: float, volume: float = 1000) -> Bar:
    ts = datetime(2026, 6, 10, 13, 30, tzinfo=timezone.utc) + timedelta(minutes=i)
    return Bar(ts=ts, open=price, high=price + 0.1, low=price - 0.1, close=price, volume=volume)


def test_running_vwap_constant_price():
    bars = [make_bar(i, 10.0) for i in range(10)]
    vwap = running_vwap(bars)
    assert all(abs(v - 10.0) < 1e-9 for v in vwap)


def test_vwap_weights_by_volume():
    # heavy volume at 10, light at 20 -> vwap pulled toward 10
    bars = [make_bar(0, 10.0, volume=9000), make_bar(1, 20.0, volume=1000)]
    vwap = running_vwap(bars)
    assert 10.5 < vwap[-1] < 12.0


def test_tracker_matches_batch():
    bars = [make_bar(i, 10 + i * 0.5, volume=500 + 100 * i) for i in range(20)]
    batch = running_vwap(bars)
    tracker = VwapTracker()
    incremental = [tracker.update(b) for b in bars]
    assert all(abs(a - b) < 1e-9 for a, b in zip(batch, incremental))


def test_prior_day_seed_continues_accumulating():
    prior = [make_bar(i, 10.0, volume=1000) for i in range(50)]
    tracker = VwapTracker()
    tracker.seed(prior)
    assert abs(tracker.value - 10.0) < 1e-9
    # today's trading at 14 should drift the anchored line up, slowly
    for i in range(50):
        tracker.update(make_bar(100 + i, 14.0, volume=1000))
    assert 11.9 < tracker.value < 12.1
