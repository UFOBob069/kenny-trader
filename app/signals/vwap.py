"""VWAP math.

Two lines matter, exactly like Kenny's chart:
  - Blue line:   today's session VWAP, reset each trading day.
  - Yellow line: "prior day VWAP" — an anchored VWAP whose anchor is the start of
    the PRIOR session and which keeps accumulating through today. That is why it
    drifts during the day instead of being a flat level.
"""
from __future__ import annotations

from app.models import Bar


def running_vwap(bars: list[Bar]) -> list[float]:
    """Running VWAP across the given bars (anchor = first bar)."""
    out: list[float] = []
    cum_pv = 0.0
    cum_v = 0.0
    for b in bars:
        v = max(b.volume, 0.0)
        cum_pv += b.typical_price * v
        cum_v += v
        out.append(cum_pv / cum_v if cum_v > 0 else b.close)
    return out


class VwapTracker:
    """Incremental VWAP, fed one bar at a time."""

    def __init__(self) -> None:
        self.cum_pv = 0.0
        self.cum_v = 0.0
        self.value: float | None = None

    def seed(self, bars: list[Bar]) -> None:
        """Pre-load history (e.g. the prior session for the yellow line)."""
        for b in bars:
            self.update(b)

    def update(self, bar: Bar) -> float:
        v = max(bar.volume, 0.0)
        self.cum_pv += bar.typical_price * v
        self.cum_v += v
        self.value = self.cum_pv / self.cum_v if self.cum_v > 0 else bar.close
        return self.value
