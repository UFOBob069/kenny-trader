from fastapi.testclient import TestClient
from unittest.mock import AsyncMock

from app.api.server import app
from app.api.technicals import research
from app.data.daily_research import ResearchDataError


def test_routes_are_read_only_and_validate_inputs(monkeypatch):
    scan = AsyncMock(return_value={'items':[]})
    monkeypatch.setattr(research, 'scan', scan)
    client = TestClient(app)  # no lifespan: never connects a broker
    assert client.get('/technicals').status_code == 200
    assert client.post('/api/technicals/scan', json={'symbols':'AAPL MSFT'}).status_code == 200
    assert scan.call_args.args[0] == ['AAPL','MSFT']
    assert client.get('/api/technicals/chart/AAPL?years=6').status_code == 422
    assert client.get('/api/technicals/chart/AAPL?anchor=invalid').status_code == 422
    assert client.get('/api/technicals/chart/AAPL?anchor=custom').status_code == 422
    assert client.get('/api/technicals/chart/AAPL?anchor=custom&anchor_date=nonsense').status_code == 422
    assert client.get('/api/technicals/chart/%3Cscript%3E').status_code == 422
    assert client.post('/api/technicals/scan', json={'symbols':'bad!'}).status_code == 422


def test_chart_provider_failure_is_actionable(monkeypatch):
    monkeypatch.setattr(research, 'chart', AsyncMock(side_effect=ResearchDataError('Feed access denied.')))
    client = TestClient(app)
    response = client.get('/api/technicals/chart/AAPL')
    assert response.status_code == 503
    assert response.json()['detail'] == 'Feed access denied.'
