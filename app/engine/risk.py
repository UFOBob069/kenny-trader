"""Risk manager: daily limits and position sizing."""
from __future__ import annotations

import logging
import math
from datetime import date

from app.models import Signal
from app.engine.execution_policy import paper_execution_allowed

log = logging.getLogger(__name__)


class RuntimeRules:
    """Mutable copy of the trading rules, editable from the dashboard."""

    def __init__(self, cfg) -> None:
        self.auto_trade_enabled: bool = cfg.auto_trade_enabled and paper_execution_allowed()
        self.auto_trade_threshold: float = cfg.auto_trade_threshold
        self.max_trades_per_day: int = cfg.max_trades_per_day
        self.max_daily_loss: float = cfg.max_daily_loss
        self.risk_per_trade: float = cfg.risk_per_trade
        self.max_position_size: float = cfg.max_position_size
        self.min_market_cap_millions: float = 500.0  # 0 = show all; otherwise floor in $M
        self.scan_russell_1000_only: bool = True  # NYSE/Nasdaq names in Russell 1000

    @property
    def min_market_cap_floor_usd(self) -> float:
        return self.min_market_cap_millions * 1_000_000 if self.min_market_cap_millions > 0 else 0.0

    def as_dict(self) -> dict:
        d = dict(self.__dict__)
        d["min_market_cap_floor_usd"] = self.min_market_cap_floor_usd
        return d

    def update(self, patch: dict) -> None:
        if "execution_mode" in patch or "alpaca_paper" in patch or "broker" in patch:
            raise ValueError("Execution mode is not dashboard-editable; live trading is unsupported.")
        if patch.get("auto_trade_enabled") and not paper_execution_allowed():
            raise ValueError("Automation is available only in Alpaca paper mode.")
        limits = {'auto_trade_threshold': (0, 100), 'max_trades_per_day': (1, 100),
                  'max_daily_loss': (1, 100000), 'risk_per_trade': (1, 10000),
                  'max_position_size': (1, 1000000), 'min_market_cap_millions': (0, 10000000)}
        changes = {}
        for k, v in patch.items():
            if k in ('auto_trade_enabled', 'scan_russell_1000_only'):
                if not isinstance(v, bool):
                    raise ValueError(f'{k} must be a boolean')
                changes[k] = v
            elif k in limits:
                if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
                    raise ValueError(f'{k} must be a finite number')
                low, high = limits[k]
                if not low <= v <= high or (k == 'max_trades_per_day' and int(v) != v):
                    raise ValueError(f'{k} must be between {low} and {high}')
                changes[k] = int(v) if k == 'max_trades_per_day' else float(v)
            else:
                raise ValueError(f'Unknown setting: {k}')
        for k, v in changes.items():
            setattr(self, k, v)


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
