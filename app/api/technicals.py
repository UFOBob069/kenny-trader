"""Research endpoints. This router has no order-placement dependencies."""
from datetime import date, datetime, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.config import settings
from app.data.daily_research import DEFAULT_SYMBOLS, ET, DailyResearch, ResearchDataError, symbols_from_text
from app.engine.technical_alerts import AlertConfig, TechnicalAlerts
from app.db.technical_alerts import AlertStorageError

router = APIRouter(prefix='/api/technicals')
research = DailyResearch()
alerts = TechnicalAlerts(research)


class AlertSettingsRequest(AlertConfig):
    revision: int = Field(ge=0)


class ReadAlertsRequest(BaseModel):
    ids: list[str] = Field(max_length=500)


async def alert_result(operation):
    try:
        return await operation
    except AlertStorageError as exc:
        raise HTTPException(503, str(exc)) from None
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from None


@router.get('/alerts')
async def get_alerts():
    return await alert_result(alerts.snapshot())


@router.put('/alerts')
async def configure_alerts(body: AlertSettingsRequest):
    config = AlertConfig.model_validate(body.model_dump(exclude={'revision'}))
    return await alert_result(alerts.configure(config, body.revision))


@router.post('/alerts/check')
async def check_alerts():
    return await alert_result(alerts.check())


@router.post('/alerts/read')
async def read_alerts(body: ReadAlertsRequest):
    return await alert_result(alerts.mark_read(set(body.ids)))


class ScanRequest(BaseModel):
    symbols: str = Field(default=' '.join(DEFAULT_SYMBOLS), min_length=1, max_length=1000)


def ticker(value):
    try:
        values = symbols_from_text(value)
        if len(values) != 1:
            raise ValueError('Choose one ticker.')
        return values[0]
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None


@router.get('/config')
def configuration():
    return dict(default_symbols=DEFAULT_SYMBOLS, feed=settings.alpaca_data_feed,
                history_configured=bool(settings.alpaca_api_key and settings.alpaca_secret_key),
                earnings_configured=bool(settings.finnhub_api_key), score_version='daily-v4-volatility', refresh_seconds=60)


@router.post('/scan')
async def scan(body: ScanRequest):
    try:
        symbols = symbols_from_text(body.symbols)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    try:
        return await research.scan(symbols)
    except ResearchDataError as exc:
        raise HTTPException(503, str(exc)) from None


@router.get('/chart/{symbol}')
async def chart(symbol: str, years: Annotated[int, Query(ge=1, le=5)] = 1,
                anchor: Literal['swing_high', 'swing_low', 'earnings', 'ytd', 'custom'] = 'swing_high',
                anchor_date: date | None = None):
    symbol = ticker(symbol)
    if anchor == 'custom' and anchor_date is None:
        raise HTTPException(422, 'Choose an anchor date.')
    try:
        return await research.chart(symbol, years, anchor, anchor_date.isoformat() if anchor_date else None)
    except ResearchDataError as exc:
        raise HTTPException(503, str(exc)) from None


@router.get('/earnings/{symbol}')
async def earnings(symbol: str, years: Annotated[int, Query(ge=1, le=5)] = 1):
    symbol = ticker(symbol)
    today = datetime.now(ET).date()
    return await research.earnings(symbol, today - timedelta(days=years * 366), today + timedelta(days=90))
