from datetime import date
import pytest
from app.engine.trade_plan import daily_trade_plan


def inputs(bear=False):
    summary = dict(eligible=True, score=80, direction='bearish' if bear else 'bullish', as_of='2026-10-16',
                   atr=1, trigger={'level':100, 'label':'Price / SMA 200'}, sma={'20':100}, next_earnings={'date':'2026-11-01'})
    bars = [dict(high=101, low=99, close=100)] * 60
    return summary, bars


@pytest.mark.parametrize('bear', [True, False])
def test_plan_geometry_and_defined_risk(bear):
    summary, bars = inputs(bear)
    plan = daily_trade_plan(summary, bars, date(2026, 10, 17))
    assert plan['status'] == 'conditional' and plan['execution'] == 'research_only'
    assert (plan['target'] < plan['entry'] < plan['stop']) if bear else (plan['stop'] < plan['entry'] < plan['target'])
    assert abs(plan['reward_risk'] - 2) < .02


@pytest.mark.parametrize('field,value', [('eligible', False), ('score', 0), ('atr', float('nan')), ('as_of', '2026-10-01')])
def test_unqualified_or_stale_data_gets_no_trade(field, value):
    summary, bars = inputs()
    summary[field] = value
    plan = daily_trade_plan(summary, bars, date(2026, 10, 17))
    assert plan['status'] == 'unavailable' and 'entry' not in plan


def test_earnings_and_nearby_resistance_produce_wait():
    summary, bars = inputs()
    summary['next_earnings'] = {'date':'2026-10-19'}
    bars = [*bars[:-2], dict(high=102, low=99, close=100), bars[-1]]
    plan = daily_trade_plan(summary, bars, date(2026, 10, 17))
    assert plan['status'] == 'wait'
    assert len(plan['reasons']) == 2


def test_unknown_earnings_disclosed_and_plan_does_not_depend_on_chart_range():
    summary, bars = inputs()
    summary.pop('next_earnings')
    plan = daily_trade_plan(summary, bars, date(2026, 10, 17))
    assert any('unconfirmed' in w for w in plan['warnings'])
    assert plan == daily_trade_plan(summary, bars * 5, date(2026, 10, 17))
