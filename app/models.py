from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Optional
from uuid import uuid4

from pydantic import BaseModel, Field


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Bar(BaseModel):
    ts: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float

    @property
    def typical_price(self) -> float:
        return (self.high + self.low + self.close) / 3.0


class Direction(str, Enum):
    LONG = "LONG"
    SHORT = "SHORT"


class SetupType(str, Enum):
    FAUX_SHOW_BRO = "FAUX_SHOW_BRO"          # fakeout-shakeout-breakout long
    VWAP_BREAKDOWN = "VWAP_BREAKDOWN"        # extended move loses VWAP, short


class SignalStatus(str, Enum):
    PENDING = "PENDING"        # awaiting manual approval
    APPROVED = "APPROVED"
    IGNORED = "IGNORED"
    AUTO_EXECUTED = "AUTO_EXECUTED"
    EXPIRED = "EXPIRED"
    REJECTED = "REJECTED"      # blocked by risk manager


class Candidate(BaseModel):
    symbol: str
    gap_pct: float = 0.0
    relative_volume: float = 0.0
    price: float = 0.0
    prior_close: float = 0.0
    avg_volume: float = 0.0
    catalyst: str = ""                       # "earnings", "mover", "news"
    earnings: Optional[dict] = None          # EPS/revenue actual vs estimate
    headlines: list[str] = Field(default_factory=list)


class WatchItem(BaseModel):
    symbol: str
    catalyst: str = ""
    price: Optional[float] = None
    gap_pct: Optional[float] = None
    relative_volume: Optional[float] = None
    market_cap_usd: Optional[float] = None
    score: float = 0.0
    qualified: bool = False
    watching: bool = False                   # chart + bar feed active
    checks: dict = Field(default_factory=dict)
    earnings: Optional[dict] = None
    headlines: list[str] = Field(default_factory=list)


class ConfidenceBreakdown(BaseModel):
    technical: float = 0.0
    fundamental: float = 0.0
    ai: float = 0.0
    total: float = 0.0
    reasons: list[str] = Field(default_factory=list)
    ai_sentiment: str = "neutral"


class Signal(BaseModel):
    id: str = Field(default_factory=lambda: uuid4().hex)
    created_at: datetime = Field(default_factory=utcnow)
    symbol: str
    direction: Direction
    setup: SetupType
    entry: float
    stop: float
    target: float
    confidence: float = 0.0
    breakdown: Optional[ConfidenceBreakdown] = None
    status: SignalStatus = SignalStatus.PENDING
    candidate: Optional[Candidate] = None

    @property
    def risk_per_share(self) -> float:
        return abs(self.entry - self.stop)

    @property
    def reward_risk(self) -> float:
        r = self.risk_per_share
        return abs(self.target - self.entry) / r if r > 0 else 0.0


class TradeStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class Trade(BaseModel):
    id: str = Field(default_factory=lambda: uuid4().hex)
    signal_id: str
    symbol: str
    direction: Direction
    quantity: int
    entry: float
    stop: float
    target: float
    confidence: float
    status: TradeStatus = TradeStatus.OPEN
    opened_at: datetime = Field(default_factory=utcnow)
    closed_at: Optional[datetime] = None
    exit_price: Optional[float] = None
    current_price: Optional[float] = None
    realized_pnl: Optional[float] = None
    order_ids: list[str] = Field(default_factory=list)
    pending_exits: bool = False  # waiting for extended-hours entry fill before stop/target

    @property
    def unrealized_pnl(self) -> float:
        if self.current_price is None or self.status != TradeStatus.OPEN:
            return 0.0
        sign = 1 if self.direction == Direction.LONG else -1
        return sign * (self.current_price - self.entry) * self.quantity
