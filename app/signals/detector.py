"""Kenny-style setup detection, fed 1-minute bars.

LONG — Faux Show Bro (fakeout / shakeout / breakout):
  1. The stock breaks an established intraday low ("the foe"),
  2. recovers back above that broken low within a few bars ("the show"),
  3. then reclaims VWAP from below ("back above the VWAP, you're a buyer").
  Entry = the VWAP reclaim. Stop = the fakeout low. Target = high of day.

SHORT — VWAP breakdown after an extended move:
  1. A large move higher leaves price holding well above VWAP,
  2. price loses VWAP.
  Entry = the VWAP break. Stop = high of day. Target = prior-day VWAP.
"""
from __future__ import annotations

import math

from app.config import settings
from app.models import Bar, Candidate, Direction, SetupType, Signal
from app.signals.vwap import VwapTracker


class SetupDetector:
    def __init__(self, symbol: str, prior_day_bars: list[Bar] | None = None) -> None:
        self.symbol = symbol
        self.bars: list[Bar] = []
        self.vwap = VwapTracker()                  # blue line: today only
        self.prior_vwap = VwapTracker()            # yellow line: anchored prior session
        self.has_prior = bool(prior_day_bars)
        if prior_day_bars:
            self.prior_vwap.seed(prior_day_bars)

        self.vwap_series: list[float] = []
        self.prior_vwap_series: list[float] = []

        self.hod = -math.inf
        self.lod = math.inf
        self.lod_bar_index = -1

        # fakeout state
        self.broken_low: float | None = None       # the low that got broken
        self.fakeout_low: float | None = None      # the new extreme printed during the break
        self.fakeout_bar_index = -1
        self.shakeout_confirmed = False

        # short state
        self.bars_above_vwap = 0

        self._emitted_this_bar: list[Signal] = []

    # ------------------------------------------------------------------ #

    def on_bar(self, bar: Bar, candidate: Candidate | None = None) -> list[Signal]:
        self._emitted_this_bar = []
        prev_close = self.bars[-1].close if self.bars else None
        prev_vwap = self.vwap.value

        self.bars.append(bar)
        vwap = self.vwap.update(bar)
        self.vwap_series.append(vwap)
        if self.has_prior:
            self.prior_vwap.update(bar)
        self.prior_vwap_series.append(self.prior_vwap.value if self.has_prior else vwap)

        i = len(self.bars) - 1
        self.hod = max(self.hod, bar.high)

        warmed_up = i + 1 > settings.detector_warmup_bars

        # --- fakeout: break of an established low -------------------------
        if warmed_up and bar.low < self.lod and i - self.lod_bar_index >= 2:
            self.broken_low = self.lod
            self.fakeout_low = bar.low
            self.fakeout_bar_index = i
            self.shakeout_confirmed = False

        if bar.low < self.lod:
            self.lod = bar.low
            self.lod_bar_index = i
        self.lod = min(self.lod, bar.low)

        # --- shakeout: quick recovery above the broken low -----------------
        if (
            self.broken_low is not None
            and not self.shakeout_confirmed
            and bar.close > self.broken_low
            and i - self.fakeout_bar_index <= settings.shakeout_recovery_bars
        ):
            self.shakeout_confirmed = True

        # discard stale fakeouts that never recovered
        if (
            self.broken_low is not None
            and not self.shakeout_confirmed
            and i - self.fakeout_bar_index > settings.shakeout_recovery_bars
        ):
            self.broken_low = None
            self.fakeout_low = None

        # --- crosses --------------------------------------------------------
        crossed_above = (
            prev_close is not None and prev_vwap is not None
            and prev_close <= prev_vwap and bar.close > vwap
        )
        crossed_below = (
            prev_close is not None and prev_vwap is not None
            and prev_close >= prev_vwap and bar.close < vwap
        )

        # --- LONG: shakeout confirmed, then VWAP reclaim ---------------------
        if warmed_up and self.shakeout_confirmed and crossed_above and self.fakeout_low is not None:
            entry = bar.close
            stop = self.fakeout_low
            risk = entry - stop
            # target HOD, unless the reclaim bar itself printed the high — then 2R
            target = self.hod if self.hod - entry >= risk * settings.min_reward_risk else entry + 2.0 * risk
            sig = self._make_signal(Direction.LONG, SetupType.FAUX_SHOW_BRO, entry, stop, target, candidate)
            if sig:
                self._emitted_this_bar.append(sig)
            self.shakeout_confirmed = False
            self.broken_low = None
            self.fakeout_low = None

        # --- SHORT: extended above VWAP, then loses it ------------------------
        extended = vwap > 0 and (self.hod - vwap) / vwap * 100 >= settings.short_extension_pct
        if warmed_up and crossed_below and extended and self.bars_above_vwap >= 5:
            entry = bar.close
            stop = self.hod
            pdv = self.prior_vwap.value if self.has_prior else None
            target = pdv if pdv is not None and pdv < entry else entry - 2.0 * (stop - entry)
            sig = self._make_signal(Direction.SHORT, SetupType.VWAP_BREAKDOWN, entry, stop, target, candidate)
            if sig:
                self._emitted_this_bar.append(sig)

        self.bars_above_vwap = self.bars_above_vwap + 1 if bar.close > vwap else 0

        return self._emitted_this_bar

    # ------------------------------------------------------------------ #

    def _make_signal(
        self,
        direction: Direction,
        setup: SetupType,
        entry: float,
        stop: float,
        target: float,
        candidate: Candidate | None,
    ) -> Signal | None:
        risk = abs(entry - stop)
        if risk <= 0:
            return None
        reward = abs(target - entry)
        if reward / risk < settings.min_reward_risk:
            return None
        return Signal(
            symbol=self.symbol,
            direction=direction,
            setup=setup,
            entry=round(entry, 2),
            stop=round(stop, 2),
            target=round(target, 2),
            candidate=candidate,
        )

    # ------------------------------------------------------------------ #

    def chart_payload(self) -> dict:
        """Bars + both VWAP lines, shaped for the dashboard chart."""
        return {
            "symbol": self.symbol,
            "bars": [
                {
                    "time": int(b.ts.timestamp()),
                    "open": b.open, "high": b.high, "low": b.low, "close": b.close,
                    "volume": b.volume,
                }
                for b in self.bars
            ],
            "vwap": [
                {"time": int(b.ts.timestamp()), "value": round(v, 4)}
                for b, v in zip(self.bars, self.vwap_series)
            ],
            "prior_vwap": [
                {"time": int(b.ts.timestamp()), "value": round(v, 4)}
                for b, v in zip(self.bars, self.prior_vwap_series)
                if v is not None
            ],
        }
