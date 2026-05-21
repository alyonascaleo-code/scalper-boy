import pandas as pd
import numpy as np
import logging

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────
#  ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ─────────────────────────────────────────────

def _local_highs(series: pd.Series, window: int = 3) -> pd.Series:
    """Индекс True там, где локальный максимум."""
    return (series == series.rolling(window * 2 + 1, center=True).max())


def _local_lows(series: pd.Series, window: int = 3) -> pd.Series:
    """Индекс True там, где локальный минимум."""
    return (series == series.rolling(window * 2 + 1, center=True).min())


# ─────────────────────────────────────────────
#  ПАТТЕРНЫ
# ─────────────────────────────────────────────

def detect_bull_flag(df: pd.DataFrame) -> dict:
    """
    Бычий флаг: сильный рост (флагшток) → консолидация с небольшим откатом вниз.
    Сигнал: LONG на пробитии верхней границы консолидации.
    """
    if len(df) < 30:
        return {"found": False}

    recent = df.tail(30)
    close = recent["close"].values
    volume = recent["volume"].values

    # Флагшток: первые 10 свечей — рост > 0.8%
    pole = close[9] / close[0] - 1
    if pole < 0.008:
        return {"found": False}

    # Флаг: последние 15 свечей — консолидация (диапазон < 0.5%)
    flag_segment = close[10:25]
    flag_range = (max(flag_segment) - min(flag_segment)) / close[10]
    if flag_range > 0.005:
        return {"found": False}

    # Объём на флагштоке выше среднего
    pole_vol = volume[:10].mean()
    flag_vol = volume[10:25].mean()
    if pole_vol < flag_vol * 1.2:
        return {"found": False}

    return {
        "found":       True,
        "pattern":     "Bull Flag 🚩",
        "direction":   "LONG",
        "description": f"Флагшток +{pole*100:.2f}%, консолидация {flag_range*100:.2f}%",
        "confidence":  15,
    }


def detect_bear_flag(df: pd.DataFrame) -> dict:
    """Медвежий флаг: сильное падение → консолидация → продолжение падения."""
    if len(df) < 30:
        return {"found": False}

    recent = df.tail(30)
    close = recent["close"].values
    volume = recent["volume"].values

    pole = 1 - close[9] / close[0]
    if pole < 0.008:
        return {"found": False}

    flag_segment = close[10:25]
    flag_range = (max(flag_segment) - min(flag_segment)) / close[10]
    if flag_range > 0.005:
        return {"found": False}

    pole_vol = volume[:10].mean()
    flag_vol = volume[10:25].mean()
    if pole_vol < flag_vol * 1.2:
        return {"found": False}

    return {
        "found":       True,
        "pattern":     "Bear Flag 🚩",
        "direction":   "SHORT",
        "description": f"Флагшток -{pole*100:.2f}%, консолидация {flag_range*100:.2f}%",
        "confidence":  15,
    }


def detect_head_and_shoulders(df: pd.DataFrame) -> dict:
    """
    Голова и плечи (разворот вниз).
    Ищем: левое плечо, голова (выше), правое плечо (≈ левому), пробой линии шеи.
    """
    if len(df) < 40:
        return {"found": False}

    close = df["close"].tail(40).values

    # Находим 3 локальных максимума
    peaks = []
    for i in range(2, len(close) - 2):
        if close[i] > close[i-1] and close[i] > close[i-2] and \
           close[i] > close[i+1] and close[i] > close[i+2]:
            peaks.append((i, close[i]))

    if len(peaks) < 3:
        return {"found": False}

    # Берём последние 3 пика
    l_sh, head, r_sh = peaks[-3], peaks[-2], peaks[-1]

    # Голова должна быть выше плеч
    if not (head[1] > l_sh[1] and head[1] > r_sh[1]):
        return {"found": False}

    # Плечи примерно на одном уровне (±1.5%)
    shoulder_diff = abs(l_sh[1] - r_sh[1]) / l_sh[1]
    if shoulder_diff > 0.015:
        return {"found": False}

    # Текущая цена ниже правого плеча (пробой шеи)
    neckline = min(l_sh[1], r_sh[1]) * 0.99
    if close[-1] > neckline:
        return {"found": False}

    return {
        "found":       True,
        "pattern":     "Head & Shoulders 👤",
        "direction":   "SHORT",
        "description": f"Голова {head[1]:.4f}, плечи {l_sh[1]:.4f}/{r_sh[1]:.4f}",
        "confidence":  20,
    }


def detect_inverse_head_and_shoulders(df: pd.DataFrame) -> dict:
    """Перевёрнутые голова и плечи (разворот вверх)."""
    if len(df) < 40:
        return {"found": False}

    close = df["close"].tail(40).values

    troughs = []
    for i in range(2, len(close) - 2):
        if close[i] < close[i-1] and close[i] < close[i-2] and \
           close[i] < close[i+1] and close[i] < close[i+2]:
            troughs.append((i, close[i]))

    if len(troughs) < 3:
        return {"found": False}

    l_sh, head, r_sh = troughs[-3], troughs[-2], troughs[-1]

    if not (head[1] < l_sh[1] and head[1] < r_sh[1]):
        return {"found": False}

    shoulder_diff = abs(l_sh[1] - r_sh[1]) / l_sh[1]
    if shoulder_diff > 0.015:
        return {"found": False}

    neckline = max(l_sh[1], r_sh[1]) * 1.01
    if close[-1] < neckline:
        return {"found": False}

    return {
        "found":       True,
        "pattern":     "Inverse H&S 🔄",
        "direction":   "LONG",
        "description": f"Впадина {head[1]:.4f}, плечи {l_sh[1]:.4f}/{r_sh[1]:.4f}",
        "confidence":  20,
    }


def detect_rising_wedge(df: pd.DataFrame) -> dict:
    """Восходящий клин (медвежий паттерн — сужение вверх)."""
    if len(df) < 20:
        return {"found": False}

    recent = df.tail(20)
    highs = recent["high"].values
    lows = recent["low"].values

    x = np.arange(len(highs))
    high_slope = np.polyfit(x, highs, 1)[0]
    low_slope = np.polyfit(x, lows, 1)[0]

    # Оба наклона вверх, нижняя линия круче (сужение)
    if not (high_slope > 0 and low_slope > 0 and low_slope > high_slope * 1.1):
        return {"found": False}

    # Диапазон сужается
    initial_range = highs[2] - lows[2]
    final_range = highs[-1] - lows[-1]
    if final_range >= initial_range * 0.8:
        return {"found": False}

    return {
        "found":       True,
        "pattern":     "Rising Wedge ↗️📉",
        "direction":   "SHORT",
        "description": f"Сужение диапазона, наклон H:{high_slope:.6f} L:{low_slope:.6f}",
        "confidence":  12,
    }


def detect_falling_wedge(df: pd.DataFrame) -> dict:
    """Нисходящий клин (бычий паттерн)."""
    if len(df) < 20:
        return {"found": False}

    recent = df.tail(20)
    highs = recent["high"].values
    lows = recent["low"].values

    x = np.arange(len(highs))
    high_slope = np.polyfit(x, highs, 1)[0]
    low_slope = np.polyfit(x, lows, 1)[0]

    # Оба наклона вниз, верхняя линия круче (сужение)
    if not (high_slope < 0 and low_slope < 0 and high_slope < low_slope * 1.1):
        return {"found": False}

    initial_range = highs[2] - lows[2]
    final_range = highs[-1] - lows[-1]
    if final_range >= initial_range * 0.8:
        return {"found": False}

    return {
        "found":       True,
        "pattern":     "Falling Wedge ↘️📈",
        "direction":   "LONG",
        "description": f"Сужение диапазона, наклон H:{high_slope:.6f} L:{low_slope:.6f}",
        "confidence":  12,
    }


def detect_double_top(df: pd.DataFrame) -> dict:
    """Двойная вершина (разворот вниз)."""
    if len(df) < 30:
        return {"found": False}

    close = df["close"].tail(30).values

    peaks = []
    for i in range(2, len(close) - 2):
        if close[i] > close[i-1] and close[i] > close[i-2] and \
           close[i] > close[i+1] and close[i] > close[i+2]:
            peaks.append((i, close[i]))

    if len(peaks) < 2:
        return {"found": False}

    p1, p2 = peaks[-2], peaks[-1]
    level_diff = abs(p1[1] - p2[1]) / p1[1]

    if level_diff > 0.008:
        return {"found": False}

    if close[-1] > p2[1] * 0.995:
        return {"found": False}

    return {
        "found":       True,
        "pattern":     "Double Top 🏔️🏔️",
        "direction":   "SHORT",
        "description": f"Два пика: {p1[1]:.4f} / {p2[1]:.4f}, разница {level_diff*100:.2f}%",
        "confidence":  18,
    }


def detect_double_bottom(df: pd.DataFrame) -> dict:
    """Двойное дно (разворот вверх)."""
    if len(df) < 30:
        return {"found": False}

    close = df["close"].tail(30).values

    troughs = []
    for i in range(2, len(close) - 2):
        if close[i] < close[i-1] and close[i] < close[i-2] and \
           close[i] < close[i+1] and close[i] < close[i+2]:
            troughs.append((i, close[i]))

    if len(troughs) < 2:
        return {"found": False}

    t1, t2 = troughs[-2], troughs[-1]
    level_diff = abs(t1[1] - t2[1]) / t1[1]

    if level_diff > 0.008:
        return {"found": False}

    if close[-1] < t2[1] * 1.005:
        return {"found": False}

    return {
        "found":       True,
        "pattern":     "Double Bottom 🏕️🏕️",
        "direction":   "LONG",
        "description": f"Два дна: {t1[1]:.4f} / {t2[1]:.4f}, разница {level_diff*100:.2f}%",
        "confidence":  18,
    }


def detect_hammer(df: pd.DataFrame) -> dict:
    """Молот — бычий разворот: длинная нижняя тень, маленькое тело сверху."""
    if len(df) < 5:
        return {"found": False}
    c = df.iloc[-1]
    body = abs(c["close"] - c["open"])
    lower_wick = min(c["open"], c["close"]) - c["low"]
    upper_wick = c["high"] - max(c["open"], c["close"])
    candle_range = c["high"] - c["low"]
    if candle_range == 0:
        return {"found": False}
    # Нижняя тень ≥ 2× тела, верхняя тень маленькая, перед этим был нисходящий тренд
    prev_trend = df["close"].iloc[-6] > df["close"].iloc[-2]
    if lower_wick >= 2 * body and upper_wick <= body * 0.5 and body / candle_range < 0.4 and prev_trend:
        return {
            "found": True, "pattern": "Молот 🔨", "direction": "LONG",
            "description": f"Длинная нижняя тень ({lower_wick:.4f}), тело {body:.4f} — отскок от дна",
            "confidence": 14,
        }
    return {"found": False}


def detect_shooting_star(df: pd.DataFrame) -> dict:
    """Падающая звезда — медвежий разворот: длинная верхняя тень, маленькое тело снизу."""
    if len(df) < 5:
        return {"found": False}
    c = df.iloc[-1]
    body = abs(c["close"] - c["open"])
    lower_wick = min(c["open"], c["close"]) - c["low"]
    upper_wick = c["high"] - max(c["open"], c["close"])
    candle_range = c["high"] - c["low"]
    if candle_range == 0:
        return {"found": False}
    prev_trend = df["close"].iloc[-6] < df["close"].iloc[-2]
    if upper_wick >= 2 * body and lower_wick <= body * 0.5 and body / candle_range < 0.4 and prev_trend:
        return {
            "found": True, "pattern": "Падающая звезда ⭐", "direction": "SHORT",
            "description": f"Длинная верхняя тень ({upper_wick:.4f}), тело {body:.4f} — отказ от роста",
            "confidence": 14,
        }
    return {"found": False}


def detect_bullish_engulfing(df: pd.DataFrame) -> dict:
    """Бычье поглощение: зелёная свеча полностью поглощает предыдущую красную."""
    if len(df) < 3:
        return {"found": False}
    prev = df.iloc[-2]
    curr = df.iloc[-1]
    prev_bearish = prev["close"] < prev["open"]
    curr_bullish = curr["close"] > curr["open"]
    engulfs = curr["open"] <= prev["close"] and curr["close"] >= prev["open"]
    if prev_bearish and curr_bullish and engulfs:
        size = abs(curr["close"] - curr["open"])
        return {
            "found": True, "pattern": "Бычье поглощение 📊", "direction": "LONG",
            "description": f"Зелёная свеча поглотила красную, размер {size:.4f}",
            "confidence": 16,
        }
    return {"found": False}


def detect_bearish_engulfing(df: pd.DataFrame) -> dict:
    """Медвежье поглощение: красная свеча полностью поглощает предыдущую зелёную."""
    if len(df) < 3:
        return {"found": False}
    prev = df.iloc[-2]
    curr = df.iloc[-1]
    prev_bullish = prev["close"] > prev["open"]
    curr_bearish = curr["close"] < curr["open"]
    engulfs = curr["open"] >= prev["close"] and curr["close"] <= prev["open"]
    if prev_bullish and curr_bearish and engulfs:
        size = abs(curr["open"] - curr["close"])
        return {
            "found": True, "pattern": "Медвежье поглощение 📉", "direction": "SHORT",
            "description": f"Красная свеча поглотила зелёную, размер {size:.4f}",
            "confidence": 16,
        }
    return {"found": False}


def detect_morning_star(df: pd.DataFrame) -> dict:
    """Утренняя звезда — 3 свечи: красная + маленькая + зелёная (бычий разворот)."""
    if len(df) < 4:
        return {"found": False}
    c1, c2, c3 = df.iloc[-3], df.iloc[-2], df.iloc[-1]
    c1_bear = c1["close"] < c1["open"] and abs(c1["close"] - c1["open"]) > abs(c2["close"] - c2["open"]) * 2
    c2_small = abs(c2["close"] - c2["open"]) / (c2["high"] - c2["low"] + 1e-9) < 0.4
    c3_bull = c3["close"] > c3["open"] and c3["close"] > (c1["open"] + c1["close"]) / 2
    if c1_bear and c2_small and c3_bull:
        return {
            "found": True, "pattern": "Утренняя звезда 🌅", "direction": "LONG",
            "description": "Три свечи: красная → дожи → зелёная — разворот тренда вверх",
            "confidence": 18,
        }
    return {"found": False}


def detect_evening_star(df: pd.DataFrame) -> dict:
    """Вечерняя звезда — 3 свечи: зелёная + маленькая + красная (медвежий разворот)."""
    if len(df) < 4:
        return {"found": False}
    c1, c2, c3 = df.iloc[-3], df.iloc[-2], df.iloc[-1]
    c1_bull = c1["close"] > c1["open"] and abs(c1["close"] - c1["open"]) > abs(c2["close"] - c2["open"]) * 2
    c2_small = abs(c2["close"] - c2["open"]) / (c2["high"] - c2["low"] + 1e-9) < 0.4
    c3_bear = c3["close"] < c3["open"] and c3["close"] < (c1["open"] + c1["close"]) / 2
    if c1_bull and c2_small and c3_bear:
        return {
            "found": True, "pattern": "Вечерняя звезда 🌆", "direction": "SHORT",
            "description": "Три свечи: зелёная → дожи → красная — разворот тренда вниз",
            "confidence": 18,
        }
    return {"found": False}


def detect_three_white_soldiers(df: pd.DataFrame) -> dict:
    """Три белых солдата — 3 бычьих свечи подряд с растущим закрытием."""
    if len(df) < 5:
        return {"found": False}
    c1, c2, c3 = df.iloc[-3], df.iloc[-2], df.iloc[-1]
    all_bull = c1["close"] > c1["open"] and c2["close"] > c2["open"] and c3["close"] > c3["open"]
    rising = c2["close"] > c1["close"] and c3["close"] > c2["close"]
    bodies_ok = (abs(c3["close"] - c3["open"]) > abs(c1["close"] - c1["open"]) * 0.7)
    if all_bull and rising and bodies_ok:
        gain = (c3["close"] / c1["open"] - 1) * 100
        return {
            "found": True, "pattern": "Три белых солдата 💪", "direction": "LONG",
            "description": f"3 бычьих свечи подряд, рост +{gain:.2f}% — сильный восходящий импульс",
            "confidence": 16,
        }
    return {"found": False}


def detect_three_black_crows(df: pd.DataFrame) -> dict:
    """Три чёрных вороны — 3 медвежьих свечи подряд с падением."""
    if len(df) < 5:
        return {"found": False}
    c1, c2, c3 = df.iloc[-3], df.iloc[-2], df.iloc[-1]
    all_bear = c1["close"] < c1["open"] and c2["close"] < c2["open"] and c3["close"] < c3["open"]
    falling = c2["close"] < c1["close"] and c3["close"] < c2["close"]
    bodies_ok = (abs(c3["close"] - c3["open"]) > abs(c1["close"] - c1["open"]) * 0.7)
    if all_bear and falling and bodies_ok:
        drop = (1 - c3["close"] / c1["open"]) * 100
        return {
            "found": True, "pattern": "Три чёрных вороны 🐦‍⬛", "direction": "SHORT",
            "description": f"3 медвежьих свечи подряд, падение -{drop:.2f}% — сильный нисходящий импульс",
            "confidence": 16,
        }
    return {"found": False}


def detect_rsi_divergence(df: pd.DataFrame) -> dict:
    """RSI дивергенция — цена идёт в одну сторону, RSI в другую."""
    if len(df) < 20:
        return {"found": False}
    try:
        recent = df.tail(20)
        prices = recent["close"].values
        rsi_vals = recent["rsi"].values if "rsi" in recent.columns else None
        if rsi_vals is None:
            return {"found": False}

        # Ищем последние два локальных максимума/минимума цены
        price_highs = [(i, prices[i]) for i in range(2, len(prices)-1)
                       if prices[i] > prices[i-1] and prices[i] > prices[i+1]]
        price_lows  = [(i, prices[i]) for i in range(2, len(prices)-1)
                       if prices[i] < prices[i-1] and prices[i] < prices[i+1]]

        # Медвежья дивергенция: цена выше, RSI ниже
        if len(price_highs) >= 2:
            h1, h2 = price_highs[-2], price_highs[-1]
            if h2[1] > h1[1] and rsi_vals[h2[0]] < rsi_vals[h1[0]] - 3:
                return {
                    "found": True, "pattern": "Медвежья RSI дивергенция 📉", "direction": "SHORT",
                    "description": f"Цена растёт ({h1[1]:.4f}→{h2[1]:.4f}), RSI падает — скрытая слабость",
                    "confidence": 18,
                }

        # Бычья дивергенция: цена ниже, RSI выше
        if len(price_lows) >= 2:
            l1, l2 = price_lows[-2], price_lows[-1]
            if l2[1] < l1[1] and rsi_vals[l2[0]] > rsi_vals[l1[0]] + 3:
                return {
                    "found": True, "pattern": "Бычья RSI дивергенция 📈", "direction": "LONG",
                    "description": f"Цена падает ({l1[1]:.4f}→{l2[1]:.4f}), RSI растёт — скрытая сила",
                    "confidence": 18,
                }
    except Exception:
        pass
    return {"found": False}


def detect_volume_spike(df: pd.DataFrame) -> dict:
    """Всплеск объёма — объём в 2+ раза выше среднего подтверждает движение."""
    if len(df) < 10 or "volume_ratio" not in df.columns:
        return {"found": False}
    last = df.iloc[-1]
    vol_ratio = last.get("volume_ratio", 1.0)
    if vol_ratio >= 2.0:
        direction = "LONG" if last["close"] > last["open"] else "SHORT"
        label = "бычий" if direction == "LONG" else "медвежий"
        return {
            "found": True, "pattern": f"Всплеск объёма 🔊", "direction": direction,
            "description": f"Объём ×{vol_ratio:.1f} от среднего при {label} закрытии — сильное движение",
            "confidence": 14,
        }
    return {"found": False}


# ─────────────────────────────────────────────
#  ГЛАВНАЯ ФУНКЦИЯ
# ─────────────────────────────────────────────

DETECTORS = [
    detect_bull_flag,
    detect_bear_flag,
    detect_head_and_shoulders,
    detect_inverse_head_and_shoulders,
    detect_rising_wedge,
    detect_falling_wedge,
    detect_double_top,
    detect_double_bottom,
    detect_hammer,
    detect_shooting_star,
    detect_bullish_engulfing,
    detect_bearish_engulfing,
    detect_morning_star,
    detect_evening_star,
    detect_three_white_soldiers,
    detect_three_black_crows,
    detect_rsi_divergence,
    detect_volume_spike,
]


def detect_all_patterns(df: pd.DataFrame) -> list:
    """
    Запустить все детекторы паттернов.
    Возвращает список найденных паттернов с их данными.
    """
    found = []
    for detector in DETECTORS:
        try:
            result = detector(df)
            if result.get("found"):
                found.append(result)
        except Exception as e:
            logger.warning(f"Pattern detector error ({detector.__name__}): {e}")
    return found
