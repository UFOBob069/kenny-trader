"""Order placement result from broker clients."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class OrderPlacement:
    order_ids: list[str] = field(default_factory=list)
    pending_exits: bool = False  # extended-hours entry submitted; attach stop/target on fill
