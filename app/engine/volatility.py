"""Causal daily volatility studies and bounded research-score evidence."""
import numpy as np
import pandas as pd
from ta.volatility import BollingerBands, DonchianChannel, KeltnerChannel


# OLS endpoint weights avoid refitting the same 20-period design for every bar.
_X = np.column_stack((np.ones(20), np.arange(20)))
_ENDPOINT = np.array([1., 19.]) @ np.linalg.pinv(_X)


def add_volatility(data):
    bb = BollingerBands(data.close, window=20, window_dev=2)
    for key, values in [('bb_upper', bb.bollinger_hband()), ('bb_lower', bb.bollinger_lband()),
                        ('bb_middle', bb.bollinger_mavg()), ('bb_width', bb.bollinger_wband())]:
        data[key] = values
    dc = DonchianChannel(data.high, data.low, data.close, window=20)
    data['dc_upper'] = dc.donchian_channel_hband().shift(1)
    data['dc_lower'] = dc.donchian_channel_lband().shift(1)
    data['dc_middle'] = dc.donchian_channel_mband().shift(1)
    data['kc_upper'] = data['kc_lower'] = data['kc_middle'] = float('nan')
    if len(data) >= 20:
        kc = KeltnerChannel(data.high, data.low, data.close, window=20, window_atr=20,
                            original_version=False, multiplier=1.5)
        data['kc_upper'], data['kc_lower'], data['kc_middle'] = (
            kc.keltner_channel_hband(), kc.keltner_channel_lband(), kc.keltner_channel_mband())
    valid = data.bb_upper.notna() & data.kc_upper.notna()
    inside = (data.bb_upper < data.kc_upper) & (data.bb_lower > data.kc_lower)
    data['squeeze_on'] = inside.astype(object).where(valid, None)
    data['squeeze_release'] = valid & valid.shift(1, fill_value=False) & ~inside & inside.shift(1, fill_value=False)
    delta = data.close - (dc.donchian_channel_mband() + data.bb_middle) / 2
    data['squeeze_momentum'] = float('nan')
    if len(data) >= 20:
        data.loc[data.index[19:], 'squeeze_momentum'] = np.convolve(delta.to_numpy(), _ENDPOINT[::-1], mode='valid')
    data['atr_change5'] = (data.atr / data.atr.shift(5).replace(0, np.nan) - 1) * 100
    data['bb_narrow'] = data.bb_width <= data.bb_width.shift(1).rolling(126).quantile(.2)
    data['compression'] = (inside & valid) | (data.bb_narrow & (data.atr_change5 < 0))
    return data


def finite(value):
    return round(float(value), 4) if pd.notna(value) and np.isfinite(value) else None


def volatility_context(data):
    if data.empty:
        return dict(available=False)
    last = data.iloc[-1]
    available = pd.notna(last.kc_upper)
    return dict(available=bool(available), bb_width_pct=finite(last.bb_width),
                bb_narrow=bool(last.bb_narrow), bb_contracting=bool(len(data) > 5 and last.bb_width < data.bb_width.iloc[-6]),
                atr=finite(last.atr), atr_change5_pct=finite(last.atr_change5),
                donchian_high=finite(last.dc_upper), donchian_low=finite(last.dc_lower),
                squeeze='unavailable' if not available else 'on' if last.squeeze_on else 'released' if last.squeeze_release else 'off',
                momentum=finite(last.squeeze_momentum),
                keltner_method='EMA20 close +/- 1.5 x Wilder ATR20')


def volatility_score(data, sign):
    last = data.iloc[-1]
    compression = (3 if last.bb_narrow and last.atr_change5 < 0 else 0) + (2 if last.squeeze_on is not None and last.squeeze_on else 0)
    recent_compression = bool(data.compression.iloc[-6:-1].any())
    boundary = last.dc_upper if sign == 1 else last.dc_lower
    donchian = 5 if recent_compression and sign * (last.close - boundary) > 0 else 0
    released = bool(data.squeeze_release.iloc[-5:].any())
    momentum = last.squeeze_momentum
    accelerating = len(data) > 1 and sign * (momentum - data.squeeze_momentum.iloc[-2]) > 0
    release = 5 if released and not last.squeeze_on and sign * momentum > 0 and accelerating and sign * (last.close - last.bb_middle) > 0 else 0
    return [
        ('Volatility compression', compression, 5, 'BB narrow + falling ATR: 3; squeeze on: 2. Neutral watch evidence.'),
        ('Donchian breakout confirmation', donchian, 5, 'Beyond prior 20-bar range after compression in prior 5 bars.'),
        ('Squeeze release confirmation', release, 5, 'Release within 5 bars + directional, accelerating momentum + price/SMA20 agreement.'),
    ]


def volatility_payload(data):
    def points(column):
        return [dict(time=r.time, value=finite(getattr(r, column))) for r in data.itertuples()
                if pd.notna(getattr(r, column))]
    return dict(
        bollinger={key: points(f'bb_{key}') for key in ('upper', 'middle', 'lower')},
        donchian={key: points(f'dc_{key}') for key in ('upper', 'middle', 'lower')},
        keltner={key: points(f'kc_{key}') for key in ('upper', 'middle', 'lower')},
        atr=points('atr'), momentum=points('squeeze_momentum'),
        squeeze=[dict(time=r.time, on=bool(r.squeeze_on), released=bool(r.squeeze_release))
                 for r in data.itertuples() if r.squeeze_on is not None],
    )
