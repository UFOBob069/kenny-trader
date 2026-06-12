"""Risk manager: daily limits and position sizing."""
from __future__ import annotations

import logging
from datetime import date

from app.models import Signal

log = logging.getLogger(__name__)


class RuntimeRules:
    """Mutable copy of the trading rules, editable from the dashboard."""

    def __init__(self, cfg) -> None:
        self.auto_trade_enabled: bool = cfg.auto_trade_enabled
        self.auto_trade_threshold: float = cfg.auto_trade_threshold
        self.max_trades_per_day: int = cfg.max_trades_per_day
        self.max_daily_loss: float = cfg.max_daily_loss
        self.risk_per_trade: float = cfg.risk_per_trade
        self.max_position_size: float = cfg.max_position_size
        self.min_market_cap_filter_enabled: bool = True
        self.min_market_cap_millions: float = 500.0  # $500M when filter is on

    @property
    def min_market_cap_floor_usd(self) -> float:
        if not self.min_market_cap_filter_enabled:
            return 0.0
        return self.min_market_cap_millions * 1_000_000

    def as_dict(self) -> dict:
        d = dict(self.__dict__)
        d["min_market_cap_floor_usd"] = self.min_market_cap_floor_usd
        return d

    def update(self, patch: dict) -> None:
        for k, v in patch.items():
            if hasattr(self, k):
                setattr(self, k, type(getattr(self, k))(v))


class RiskManager:
    def __init__(self, rules: RuntimeRules) -> None:
        self.rules = rules
        self._day = date.today()
        self.trades_today = 0
        self.realized_pnl_today = 0.0

    def _roll_day(self) -> None:
        if date.today() != self._day:
            self._day = date.today()
            self.trades_today = 0
            self.realized_pnl_today = 0.0

    def can_trade(self) -> tuple[bool, str]:
        self._roll_day()
        if self.trades_today >= self.rules.max_trades_per_day:
            return False, f"Max trades per day reached ({self.rules.max_trades_per_day})"
        if self.realized_pnl_today <= -self.rules.max_daily_loss:
            return False, f"Daily loss limit hit (${self.rules.max_daily_loss:.0f})"
        return True, ""

    def position_size(self, signal: Signal) -> int:
        """Shares such that (entry - stop) * shares <= risk_per_trade,
        capped by max_position_size dollars."""
        risk = signal.risk_per_share
        if risk <= 0:
            return 0
        by_risk = int(self.rules.risk_per_trade / risk)
        by_notional = int(self.rules.max_position_size / signal.entry) if signal.entry > 0 else 0
        return max(0, min(by_risk, by_notional))

    def record_trade_opened(self) -> None:
        self._roll_day()
        self.trades_today += 1

    def record_trade_closed(self, realized_pnl: float) -> None:
        self._roll_day()
        self.realized_pnl_today += realized_pnl
