"""Broker factory: Alpaca (default) or IBKR."""
from __future__ import annotations

from app.config import settings
from app.data.alpaca import AlpacaClient, BrokerClient


def make_broker() -> BrokerClient:
    if settings.broker.lower() == "ibkr":
        from app.data.ibkr import IbkrClient
        return IbkrClient()
    return AlpacaClient()
