"""This release permits research or Alpaca paper execution, never live trading."""
from app.config import settings


def paper_execution_allowed() -> bool:
    return settings.execution_mode == "paper" and settings.broker == "alpaca"


def require_paper_execution() -> None:
    if not paper_execution_allowed():
        raise PermissionError("Orders disabled: only Alpaca paper execution is supported.")
