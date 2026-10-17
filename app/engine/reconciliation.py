"""Idempotent accounting from cumulative, broker-reported order fills."""
from datetime import datetime, timezone
import math

from app.models import Direction, Trade, TradeStatus

TERMINAL = {'filled', 'canceled', 'expired', 'rejected', 'replaced'}


def reconcile(trade: Trade, orders: list[dict]) -> None:
    # Replace cumulative snapshots, never add the same fill again on each poll.
    snapshots = {o['id']: o for o in orders}
    entry = snapshots.get(trade.order_ids[0]) if trade.order_ids else None
    trade.pnl_verified = False
    if not entry:
        raise ValueError('Entry order missing; outcome unknown')
    sign = 1 if trade.direction == Direction.LONG else -1
    entry_side = 'buy' if sign == 1 else 'sell'
    exits = [o for oid, o in snapshots.items() if oid != entry['id']]
    for order in snapshots.values():
        qty = float(order['filled_qty'])
        price = order.get('filled_avg_price')
        if not math.isfinite(qty) or qty < 0 or (qty and (price is None or not math.isfinite(float(price)) or float(price) <= 0)):
            raise ValueError('Invalid broker fill quantity or price')
        if order['status'] == 'filled' and not qty:
            raise ValueError('Filled order has no filled quantity')
        expected = entry_side if order['id'] == entry['id'] else ('sell' if sign == 1 else 'buy')
        if order['symbol'] != trade.symbol or order['side'] != expected:
            raise ValueError('Order attribution mismatch')
    filled = float(entry['filled_qty'])
    exited = sum(float(o['filled_qty']) for o in exits)
    if exited > filled + 1e-8:
        raise ValueError('Exit fills exceed entry fills; inspect broker position')
    trade.orders = snapshots
    trade.filled_quantity = filled
    trade.exited_quantity = exited
    trade.entry_fill_price = float(entry['filled_avg_price']) if filled else None
    trade.first_fill_at = _time(entry.get('filled_at')) if filled else None
    trade.exit_price = sum(float(o['filled_qty']) * float(o['filled_avg_price'] or 0) for o in exits) / exited if exited else None
    trade.realized_pnl = round(sign * (trade.exit_price - trade.entry_fill_price) * exited, 2) if exited else None
    trade.reconciled_at = datetime.now(timezone.utc)
    trade.reconciliation_error = None
    trade.closed_at = None
    settled = all(o['status'] in TERMINAL for o in snapshots.values())
    if filled and abs(filled - exited) < 1e-8 and settled:
        times = [_time(o.get('filled_at')) for o in exits if float(o['filled_qty'])]
        if not all(times):
            raise ValueError('Exit fill timestamp missing')
        trade.closed_at = max(times)
        trade.status = TradeStatus.CLOSED
        trade.pnl_verified = True
        filled_exits = [o for o in exits if float(o['filled_qty'])]
        trade.exit_reason = ('manual' if any(o['id'] == trade.close_order_id for o in filled_exits)
                             else 'stop' if any('stop' in o['type'] for o in filled_exits) else 'target')
    elif not filled and settled:
        trade.status = TradeStatus.CANCELED
        trade.exit_reason = entry['status']
    else:
        trade.status = TradeStatus.CLOSING if trade.close_requested else TradeStatus.OPEN if filled else TradeStatus.PENDING


def _time(value):
    if not value:
        return None
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00')) if isinstance(value, str) else value
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed
