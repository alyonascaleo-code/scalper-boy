import pandas as pd
import numpy as np
from config import (
    RSI_PERIOD, EMA_FAST, EMA_SLOW, EMA_TREND,
    MACD_FAST, MACD_SLOW, MACD_SIGNAL,
    BB_PERIOD, BB_STD, ATR_PERIOD, VOLUME_MA_PERIOD
)


def calc_rsi(close: pd.Series, period: int = RSI_PERIOD) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(com=period - 1, min_periods=period).mean()
    avg_loss = loss.ewm(com=period - 1, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def calc_stoch_rsi(close: pd.Series, period: int = 14, smooth_k: int = 3, smooth_d: int = 3):
    """Стохастик RSI — показывает перекупленность/перепроданность точнее RSI."""
    rsi = calc_rsi(close, period)
    min_rsi = rsi.rolling(period).min()
    max_rsi = rsi.rolling(period).max()
    stoch = (rsi - min_rsi) / (max_rsi - min_rsi + 1e-9) * 100
    k = stoch.rolling(smooth_k).mean()
    d = k.rolling(smooth_d).mean()
    return k, d


def calc_ema(close: pd.Series, period: int) -> pd.Series:
    return close.ewm(span=period, adjust=False).mean()


def calc_macd(close: pd.Series):
    fast = calc_ema(close, MACD_FAST)
    slow = calc_ema(close, MACD_SLOW)
    macd_line = fast - slow
    signal_line = macd_line.ewm(span=MACD_SIGNAL, adjust=False).mean()
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram


def calc_bollinger_bands(close: pd.Series):
    middle = close.rolling(BB_PERIOD).mean()
    std = close.rolling(BB_PERIOD).std()
    upper = middle + BB_STD * std
    lower = middle - BB_STD * std
    return upper, middle, lower


def calc_atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = ATR_PERIOD) -> pd.Series:
    tr = pd.concat([
        high - low,
        (high - close.shift()).abs(),
        (low - close.shift()).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(com=period - 1, min_periods=period).mean()


def calc_adx(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14):
    """ADX — сила тренда. >25 = сильный тренд, >40 = очень сильный."""
    tr = pd.concat([
        high - low,
        (high - close.shift()).abs(),
        (low - close.shift()).abs(),
    ], axis=1).max(axis=1)

    up_move = high - high.shift()
    down_move = low.shift() - low

    plus_dm = up_move.where((up_move > down_move) & (up_move > 0), 0.0)
    minus_dm = down_move.where((down_move > up_move) & (down_move > 0), 0.0)

    atr_s = tr.ewm(span=period, adjust=False).mean()
    plus_di = 100 * plus_dm.ewm(span=period, adjust=False).mean() / (atr_s + 1e-9)
    minus_di = 100 * minus_dm.ewm(span=period, adjust=False).mean() / (atr_s + 1e-9)
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di + 1e-9)
    adx = dx.ewm(span=period, adjust=False).mean()
    return adx, plus_di, minus_di


def calc_cci(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 20) -> pd.Series:
    """CCI — товарный канальный индекс. >100 = перекупленность, <-100 = перепроданность."""
    typical = (high + low + close) / 3
    sma = typical.rolling(period).mean()
    mad = typical.rolling(period).apply(lambda x: np.mean(np.abs(x - np.mean(x))), raw=True)
    return (typical - sma) / (0.015 * mad + 1e-9)


def calc_obv(close: pd.Series, volume: pd.Series) -> pd.Series:
    """OBV — On Balance Volume. Показывает давление покупателей/продавцов."""
    direction = np.sign(close.diff()).fillna(0)
    return (direction * volume).cumsum()


def calc_vwap(high: pd.Series, low: pd.Series, close: pd.Series, volume: pd.Series) -> pd.Series:
    """VWAP — средневзвешенная цена по объёму. Ключевой уровень входа."""
    typical = (high + low + close) / 3
    return (typical * volume).cumsum() / (volume.cumsum() + 1e-9)


def calc_supertrend(high: pd.Series, low: pd.Series, close: pd.Series,
                    period: int = 10, multiplier: float = 3.0):
    """Supertrend — направление тренда. +1 = бычий, -1 = медвежий."""
    atr = calc_atr(high, low, close, period)
    hl2 = (high + low) / 2
    upper_band = hl2 + multiplier * atr
    lower_band = hl2 - multiplier * atr

    supertrend = pd.Series(np.nan, index=close.index)
    direction = pd.Series(1, index=close.index)

    for i in range(1, len(close)):
        prev_upper = upper_band.iloc[i - 1]
        prev_lower = lower_band.iloc[i - 1]
        curr_close = close.iloc[i]

        if curr_close > prev_upper:
            direction.iloc[i] = 1
        elif curr_close < prev_lower:
            direction.iloc[i] = -1
        else:
            direction.iloc[i] = direction.iloc[i - 1]

        supertrend.iloc[i] = lower_band.iloc[i] if direction.iloc[i] == 1 else upper_band.iloc[i]

    return supertrend, direction


def calc_volume_ma(volume: pd.Series, period: int = VOLUME_MA_PERIOD) -> pd.Series:
    return volume.rolling(period).mean()


def calc_williams_r(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    """Williams %R. < -80 = перепроданность (LONG), > -20 = перекупленность (SHORT)."""
    highest_high = high.rolling(period).max()
    lowest_low = low.rolling(period).min()
    return -100 * (highest_high - close) / (highest_high - lowest_low + 1e-9)


def add_all_indicators(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()

    # Базовые
    df["rsi"] = calc_rsi(df["close"])
    df["stoch_k"], df["stoch_d"] = calc_stoch_rsi(df["close"])

    df["ema_fast"]  = calc_ema(df["close"], EMA_FAST)
    df["ema_slow"]  = calc_ema(df["close"], EMA_SLOW)
    df["ema_trend"] = calc_ema(df["close"], EMA_TREND)

    df["macd"], df["macd_signal"], df["macd_hist"] = calc_macd(df["close"])

    df["bb_upper"], df["bb_mid"], df["bb_lower"] = calc_bollinger_bands(df["close"])
    df["bb_width"] = (df["bb_upper"] - df["bb_lower"]) / df["bb_mid"]
    df["bb_pct"]   = (df["close"] - df["bb_lower"]) / (df["bb_upper"] - df["bb_lower"] + 1e-9)

    df["atr"]     = calc_atr(df["high"], df["low"], df["close"])
    df["atr_pct"] = df["atr"] / df["close"] * 100

    # Новые индикаторы
    df["adx"], df["plus_di"], df["minus_di"] = calc_adx(df["high"], df["low"], df["close"])
    df["cci"]       = calc_cci(df["high"], df["low"], df["close"])
    df["obv"]       = calc_obv(df["close"], df["volume"])
    df["obv_ema"]   = calc_ema(df["obv"], 10)
    df["vwap"]      = calc_vwap(df["high"], df["low"], df["close"], df["volume"])
    df["williams_r"] = calc_williams_r(df["high"], df["low"], df["close"])
    df["supertrend"], df["supertrend_dir"] = calc_supertrend(df["high"], df["low"], df["close"])

    df["volume_ma"]    = calc_volume_ma(df["volume"])
    df["volume_ratio"] = df["volume"] / df["volume_ma"]

    return df
