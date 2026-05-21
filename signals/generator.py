import logging
from typing import Optional
import pandas as pd
from datetime import datetime, timezone

from config import (
    MIN_CONFIDENCE, MAX_STOP_LOSS_PCT,
    TP1_MULTIPLIER, TP2_MULTIPLIER,
    RSI_OVERSOLD, RSI_OVERBOUGHT,
    MIN_ADX, MIN_VOLUME_RATIO, MIN_MTF_CONFLUENCE,
    ACCOUNT_SIZE, RISK_PER_TRADE_PCT,
)
from indicators.calculator import add_all_indicators
from patterns.detector import detect_all_patterns
from data.sessions import get_session_info

logger = logging.getLogger(__name__)

MTF_TIMEFRAMES = ["1", "5", "15"]


def _analyze_single_tf(df: pd.DataFrame, direction: str) -> dict:
    """Анализ одного таймфрейма с учётом направления сигнала."""
    df = add_all_indicators(df)
    last = df.iloc[-1]
    prev = df.iloc[-2]

    rsi = last["rsi"]
    ema_bull = last["ema_fast"] > last["ema_slow"] > last["ema_trend"]
    ema_bear = last["ema_fast"] < last["ema_slow"] < last["ema_trend"]
    ema_partial_bull = last["ema_fast"] > last["ema_slow"]
    ema_partial_bear = last["ema_fast"] < last["ema_slow"]
    macd_bull = last["macd"] > last["macd_signal"]
    macd_cross_up = macd_bull and prev["macd"] <= prev["macd_signal"]
    macd_cross_dn = not macd_bull and prev["macd"] >= prev["macd_signal"]
    price_above_ema = last["close"] > last["ema_trend"]
    rsi_bull = rsi < 55
    rsi_bear = rsi > 45

    # Считаем подтверждения в сторону сигнала
    if direction == "LONG":
        confirms = sum([
            ema_bull or ema_partial_bull,   # EMA смотрит вверх
            macd_bull,                       # MACD выше сигнала
            price_above_ema,                 # цена выше EMA50
            rsi_bull,                        # RSI не перекуплен
        ])
    else:  # SHORT
        confirms = sum([
            ema_bear or ema_partial_bear,    # EMA смотрит вниз
            not macd_bull,                   # MACD ниже сигнала
            not price_above_ema,             # цена ниже EMA50
            rsi_bear,                        # RSI не перепродан
        ])

    if confirms >= 3:
        trend = direction          # поддерживает сигнал
    elif confirms <= 1:
        trend = "AGAINST"          # против сигнала
    else:
        trend = "NEUTRAL"

    macd_label = "↑ пересечение" if macd_cross_up else (
        "↓ пересечение" if macd_cross_dn else (
        "+ выше сигнала" if macd_bull else "− ниже сигнала"))

    return {
        "trend":           trend,
        "confirms":        confirms,
        "rsi":             round(rsi, 1),
        "ema_aligned_bull": ema_bull,
        "ema_aligned_bear": ema_bear,
        "ema_partial_bull": ema_partial_bull,
        "ema_partial_bear": ema_partial_bear,
        "price_above_ema": price_above_ema,
        "macd_label":      macd_label,
        "macd_cross_up":   macd_cross_up,
        "macd_cross_dn":   macd_cross_dn,
        "volume_ratio":    round(last["volume_ratio"], 2),
    }


def get_mtf_analysis(symbol: str, direction: str) -> dict:
    """Анализ 1m/5m/15m с направленной конфлюэнцией."""
    from data.fetcher import fetch_ohlcv

    tf_labels = {"1": "1m", "5": "5m", "15": "15m"}
    tf_results = {}
    confluence = 0

    for tf in MTF_TIMEFRAMES:
        try:
            df = fetch_ohlcv(symbol, tf, limit=100)
            if df.empty or len(df) < 55:
                continue
            analysis = _analyze_single_tf(df, direction)
            tf_results[tf_labels[tf]] = analysis
            if analysis["trend"] == direction:
                confluence += 1
        except Exception as e:
            logger.warning(f"MTF error {symbol} {tf}m: {e}")

    has_1m = "1m" in tf_results
    cross_1m = has_1m and (tf_results["1m"]["macd_cross_up"] or tf_results["1m"]["macd_cross_dn"])

    if confluence == 3:
        entry_window = "⚡ ВХОДИТЬ СЕЙЧАС — все 3 ТФ подтверждают направление"
        entry_minutes = "Окно: 1-3 минуты"
    elif confluence == 2:
        if cross_1m:
            entry_window = "✅ ВХОДИТЬ — 1m только что дал MACD-пересечение"
            entry_minutes = "Окно: 2-5 минут, не затягивать"
        else:
            entry_window = "⏳ ЖДАТЬ 1m подтверждения — 2/3 ТФ согласны"
            entry_minutes = "Ждать следующую 1m свечу в сторону сигнала"
    elif confluence == 1:
        entry_window = "⚠️ ОСТОРОЖНО — только 1/3 ТФ поддерживает"
        entry_minutes = "Лучше пропустить или ждать 5m-подтверждения"
    else:
        entry_window = "🚫 НИ ОДИН ТФ не подтверждает — входить крайне рискованно"
        entry_minutes = "Подождать разворота на 5m или 15m"

    return {
        "timeframes": tf_results,
        "confluence": confluence,
        "entry_window": entry_window,
        "entry_minutes": entry_minutes,
    }


def _score_long(df: pd.DataFrame, patterns: list) -> tuple:
    score = 0
    reasons = []
    last = df.iloc[-1]
    prev = df.iloc[-2]

    # RSI
    if last["rsi"] < RSI_OVERSOLD:
        score += 15; reasons.append(f"RSI перепродан ({last['rsi']:.1f})")
    elif last["rsi"] < 45:
        score += 7;  reasons.append(f"RSI ниже нейтрали ({last['rsi']:.1f})")

    # Stochastic RSI
    if last.get("stoch_k", 50) < 20:
        score += 12; reasons.append(f"StochRSI перепродан ({last['stoch_k']:.1f})")
    elif last.get("stoch_k", 50) < 30 and last.get("stoch_k", 50) > last.get("stoch_d", 50):
        score += 7;  reasons.append(f"StochRSI разворот вверх ({last['stoch_k']:.1f})")

    # Williams %R
    if last.get("williams_r", -50) < -80:
        score += 10; reasons.append(f"Williams %R перепродан ({last['williams_r']:.1f})")

    # CCI
    if last.get("cci", 0) < -100:
        score += 10; reasons.append(f"CCI перепродан ({last['cci']:.0f})")

    # EMA
    if last["ema_fast"] > last["ema_slow"] > last["ema_trend"]:
        score += 15; reasons.append("EMA бычье выравнивание (9>21>50)")
    elif last["ema_fast"] > last["ema_slow"]:
        score += 8;  reasons.append("EMA9 > EMA21")

    # Цена vs EMA и VWAP (Стинбарджер: входить у VWAP — ключевой уровень)
    if last["close"] > last["ema_trend"]:
        score += 5; reasons.append("Цена выше EMA50")
    vwap = last.get("vwap")
    if vwap is not None and vwap > 0:
        vwap_dist = (last["close"] - vwap) / vwap * 100
        if 0 <= vwap_dist <= 0.3:
            score += 15; reasons.append(f"Отскок от VWAP вверх — точка входа ({vwap:.4f})")
        elif last["close"] > vwap:
            score += 5; reasons.append(f"Цена выше VWAP ({vwap:.4f})")

    # Supertrend
    if last.get("supertrend_dir", 0) == 1:
        score += 12; reasons.append("Supertrend: бычий тренд ↑")

    # ADX — сила тренда (Стинбарджер: сильный тренд = надёжный сетап)
    adx = last.get("adx", 0)
    if adx > 30:
        score += 12; reasons.append(f"ADX={adx:.0f} — очень сильный тренд")
    elif adx > 20:
        score += 6; reasons.append(f"ADX={adx:.0f} — тренд подтверждён")

    # MACD
    if last["macd"] > last["macd_signal"] and prev["macd"] <= prev["macd_signal"]:
        score += 15; reasons.append("MACD бычье пересечение ↑")
    elif last["macd"] > last["macd_signal"] and last["macd_hist"] > 0:
        score += 8;  reasons.append("MACD гистограмма положительная")

    # OBV
    if last.get("obv", 0) > last.get("obv_ema", 0):
        score += 6; reasons.append("OBV растёт — объёмное давление вверх")

    # Bollinger Bands
    if last["close"] <= last["bb_lower"]:
        score += 12; reasons.append(f"Касание нижней BB — отскок ({last['bb_pct']:.0%})")
    elif last["bb_pct"] < 0.3:
        score += 5;  reasons.append("Цена в нижней трети BB")

    # Объём
    if last["volume_ratio"] > 1.5:
        score += 10; reasons.append(f"Объём ×{last['volume_ratio']:.1f} от среднего")
    elif last["volume_ratio"] > 1.2:
        score += 5;  reasons.append(f"Объём выше среднего ×{last['volume_ratio']:.1f}")

    # Паттерны
    for p in patterns:
        if p["direction"] == "LONG":
            score += p["confidence"]
            reasons.append(f"Паттерн: {p['pattern']} — {p['description']}")

    return score, reasons


def _score_short(df: pd.DataFrame, patterns: list) -> tuple:
    score = 0
    reasons = []
    last = df.iloc[-1]
    prev = df.iloc[-2]

    # RSI
    if last["rsi"] > RSI_OVERBOUGHT:
        score += 15; reasons.append(f"RSI перекуплен ({last['rsi']:.1f})")
    elif last["rsi"] > 55:
        score += 7;  reasons.append(f"RSI выше нейтрали ({last['rsi']:.1f})")

    # Stochastic RSI
    if last.get("stoch_k", 50) > 80:
        score += 12; reasons.append(f"StochRSI перекуплен ({last['stoch_k']:.1f})")
    elif last.get("stoch_k", 50) > 70 and last.get("stoch_k", 50) < last.get("stoch_d", 50):
        score += 7;  reasons.append(f"StochRSI разворот вниз ({last['stoch_k']:.1f})")

    # Williams %R
    if last.get("williams_r", -50) > -20:
        score += 10; reasons.append(f"Williams %R перекуплен ({last['williams_r']:.1f})")

    # CCI
    if last.get("cci", 0) > 100:
        score += 10; reasons.append(f"CCI перекуплен ({last['cci']:.0f})")

    # EMA
    if last["ema_fast"] < last["ema_slow"] < last["ema_trend"]:
        score += 15; reasons.append("EMA медвежье выравнивание (9<21<50)")
    elif last["ema_fast"] < last["ema_slow"]:
        score += 8;  reasons.append("EMA9 < EMA21")

    # Цена vs EMA и VWAP (Стинбарджер: входить у VWAP — ключевой уровень)
    if last["close"] < last["ema_trend"]:
        score += 5; reasons.append("Цена ниже EMA50")
    vwap = last.get("vwap")
    if vwap is not None and vwap > 0:
        vwap_dist = (vwap - last["close"]) / vwap * 100
        if 0 <= vwap_dist <= 0.3:
            score += 15; reasons.append(f"Отбой от VWAP вниз — точка входа ({vwap:.4f})")
        elif last["close"] < vwap:
            score += 5; reasons.append(f"Цена ниже VWAP ({vwap:.4f})")

    # Supertrend
    if last.get("supertrend_dir", 0) == -1:
        score += 12; reasons.append("Supertrend: медвежий тренд ↓")

    # ADX — сила тренда (Стинбарджер: сильный тренд = надёжный сетап)
    adx = last.get("adx", 0)
    if adx > 30:
        score += 12; reasons.append(f"ADX={adx:.0f} — очень сильный тренд")
    elif adx > 20:
        score += 6; reasons.append(f"ADX={adx:.0f} — тренд подтверждён")

    # MACD
    if last["macd"] < last["macd_signal"] and prev["macd"] >= prev["macd_signal"]:
        score += 15; reasons.append("MACD медвежье пересечение ↓")
    elif last["macd"] < last["macd_signal"] and last["macd_hist"] < 0:
        score += 8;  reasons.append("MACD гистограмма отрицательная")

    # OBV
    if last.get("obv", 0) < last.get("obv_ema", 0):
        score += 6; reasons.append("OBV падает — объёмное давление вниз")

    # Bollinger Bands
    if last["close"] >= last["bb_upper"]:
        score += 12; reasons.append(f"Касание верхней BB — разворот ({last['bb_pct']:.0%})")
    elif last.get("bb_pct", 0.5) > 0.7:
        score += 5;  reasons.append("Цена в верхней трети BB")

    # Объём
    if last["volume_ratio"] > 1.5:
        score += 10
        reasons.append(f"Объём ×{last['volume_ratio']:.1f} от среднего")
    elif last["volume_ratio"] > 1.2:
        score += 5
        reasons.append(f"Объём выше среднего ×{last['volume_ratio']:.1f}")

    # Паттерны
    for p in patterns:
        if p["direction"] == "SHORT":
            score += p["confidence"]
            reasons.append(f"Паттерн: {p['pattern']} — {p['description']}")

    return score, reasons


def _build_scenarios(df: pd.DataFrame, direction: str, tp1: float, tp2: float, stop_loss: float) -> dict:
    """Построить два сценария — основной и противоположный — с объяснением."""
    last = df.iloc[-1]
    rsi = last["rsi"]
    vol = last["volume_ratio"]
    macd_hist = last["macd_hist"]
    price = last["close"]
    bb_upper = last["bb_upper"]
    bb_lower = last["bb_lower"]

    if direction == "LONG":
        # Сценарий 1 — бычий (основной)
        bull_points = []
        if rsi < 45:
            bull_points.append(f"RSI={rsi:.0f} в зоне перепроданности — вероятен отскок вверх")
        if macd_hist > 0:
            bull_points.append("MACD гистограмма растёт — импульс на покупку")
        if vol > 1.2:
            bull_points.append(f"Объём ×{vol:.1f} — покупатели активны")
        if price < (bb_upper + last["bb_mid"]) / 2:
            bull_points.append("Есть пространство до верхней BB — цена не перегрета")
        if not bull_points:
            bull_points.append("EMA выровнены вверх — краткосрочный тренд на рост")
        bull_points.append(f"Цели: TP1 {tp1:.4f} → TP2 {tp2:.4f}")

        # Сценарий 2 — медвежий (риск)
        bear_points = []
        if rsi > 55:
            bear_points.append(f"RSI={rsi:.0f} не даёт подтверждения перепроданности")
        if macd_hist < 0:
            bear_points.append("MACD гистограмма отрицательная — продавцы ещё активны")
        if vol < 1.0:
            bear_points.append("Объём ниже среднего — нет подтверждения от покупателей")
        if price > last["bb_mid"]:
            bear_points.append("Цена выше средней BB — возможна коррекция вниз")
        if not bear_points:
            bear_points.append("Рынок в нейтральной зоне — коррекция всегда возможна")
        bear_points.append(f"Стоп-лосс на {stop_loss:.4f} защищает от сильного движения вниз")

        return {
            "scenario_main":  {"title": "📈 Сценарий 1 — РОСТ (основной)", "points": bull_points},
            "scenario_risk":  {"title": "📉 Сценарий 2 — КОРРЕКЦИЯ (риск)", "points": bear_points},
        }
    else:
        # Сценарий 1 — медвежий (основной)
        bear_points = []
        if rsi > 55:
            bear_points.append(f"RSI={rsi:.0f} в зоне перекупленности — вероятен откат вниз")
        if macd_hist < 0:
            bear_points.append("MACD гистограмма падает — импульс на продажу")
        if vol > 1.2:
            bear_points.append(f"Объём ×{vol:.1f} — продавцы активны")
        if price > (bb_lower + last["bb_mid"]) / 2:
            bear_points.append("Есть пространство до нижней BB — цена не перепродана")
        if not bear_points:
            bear_points.append("EMA выровнены вниз — краткосрочный тренд на падение")
        bear_points.append(f"Цели: TP1 {tp1:.4f} → TP2 {tp2:.4f}")

        # Сценарий 2 — бычий (риск)
        bull_points = []
        if rsi < 45:
            bull_points.append(f"RSI={rsi:.0f} не даёт подтверждения перекупленности")
        if macd_hist > 0:
            bull_points.append("MACD гистограмма положительная — покупатели ещё активны")
        if vol < 1.0:
            bull_points.append("Объём ниже среднего — нет подтверждения от продавцов")
        if price < last["bb_mid"]:
            bull_points.append("Цена ниже средней BB — возможен отскок вверх")
        if not bull_points:
            bull_points.append("Рынок в нейтральной зоне — разворот вверх всегда возможен")
        bull_points.append(f"Стоп-лосс на {stop_loss:.4f} защищает от сильного движения вверх")

        return {
            "scenario_main":  {"title": "📉 Сценарий 1 — ПАДЕНИЕ (основной)", "points": bear_points},
            "scenario_risk":  {"title": "📈 Сценарий 2 — ОТСКОК ВВЕРХ (риск)", "points": bull_points},
        }


def _calc_position(entry: float, stop_loss: float, confidence: int,
                   confluence: int, adx: float, atr_pct: float) -> dict:
    """
    Рассчитать рекомендуемое плечо и размер позиции.
    Принципы: риск не более RISK_PER_TRADE_PCT% депозита на сделку.
    Плечо зависит от качества сигнала и волатильности.
    """
    # ── Плечо на основе качества сигнала ──
    if confidence >= 80 and confluence == 3 and adx > 30:
        leverage = 10
        lev_why  = f"Макс. качество: уверенность {confidence}%, все 3 ТФ согласны, ADX={adx:.0f}"
    elif confidence >= 75 and confluence >= 2 and adx > 25:
        leverage = 7
        lev_why  = f"Хороший сетап: {confidence}% уверенности, {confluence}/3 ТФ, ADX={adx:.0f}"
    elif confidence >= 65 and confluence >= 2:
        leverage = 5
        lev_why  = f"Стандартный сигнал: {confidence}%, {confluence}/3 ТФ подтверждают"
    else:
        leverage = 3
        lev_why  = f"Умеренный сигнал ({confidence}%) — минимальное плечо для защиты"

    # ── Снижаем плечо при высокой волатильности ──
    if atr_pct > 3.0:
        leverage = min(leverage, 3)
        lev_why += f" | ⚠️ Волатильность высокая (ATR {atr_pct:.1f}%) — плечо снижено до {leverage}x"
    elif atr_pct > 2.0:
        leverage = min(leverage, 5)
        lev_why += f" | ATR {atr_pct:.1f}% — плечо ограничено до {leverage}x"

    # ── Размер позиции (правило Стинбарджера: риск ≤ RISK_PCT% депозита) ──
    stop_pct    = abs(entry - stop_loss) / entry * 100          # % до стопа
    risk_usd    = ACCOUNT_SIZE * (RISK_PER_TRADE_PCT / 100)     # $ риска на сделку
    position_usd = risk_usd / (stop_pct / 100)                  # размер позиции
    position_usd = min(position_usd, ACCOUNT_SIZE * leverage)   # не больше плечо×депозит
    margin_usd   = round(position_usd / leverage, 2)            # нужная маржа

    # Профит и убыток в $ при данном размере позиции
    tp1_profit = round(risk_usd * TP1_MULTIPLIER, 2)   # риск × 2
    tp2_profit = round(risk_usd * TP2_MULTIPLIER, 2)   # риск × 3
    sl_loss    = round(risk_usd, 2)                     # фиксированный риск

    # Предупреждение если маржа > 30% депозита
    margin_pct = margin_usd / ACCOUNT_SIZE * 100
    warning = ""
    if margin_pct > 30:
        warning = f"⚠️ Маржа {margin_pct:.0f}% депозита — рассмотри снижение плеча"

    return {
        "leverage":     leverage,
        "lev_why":      lev_why,
        "position_usd": round(position_usd, 2),
        "margin_usd":   margin_usd,
        "risk_usd":     sl_loss,
        "risk_pct":     RISK_PER_TRADE_PCT,
        "account_size": ACCOUNT_SIZE,
        "tp1_profit":   tp1_profit,
        "tp2_profit":   tp2_profit,
        "sl_loss":      sl_loss,
        "warning":      warning,
    }


def generate_signal(df: pd.DataFrame, symbol: str, timeframe: str) -> Optional[dict]:
    """
    Сгенерировать торговый сигнал на основе индикаторов и паттернов.
    Возвращает dict сигнала или None, если уверенность < MIN_CONFIDENCE.
    """
    try:
        df = add_all_indicators(df)
        if df.empty or len(df) < 55:
            return None

        last = df.iloc[-1]
        prev = df.iloc[-2]  # завершённая свеча

        # === ФИЛЬТРЫ СТИНБАРДЖЕРА (жёсткие ворота до скоринга) ===
        # 1. Только трендовый рынок — в боковике не входим
        adx_val = last.get("adx", 0)
        if adx_val < MIN_ADX:
            logger.debug(f"[{symbol} {timeframe}m] ADX={adx_val:.0f} < {MIN_ADX} — боковик, пропуск")
            return None

        # 2. Объём на завершённой свече (текущая — неполная, её объём занижен)
        if prev["volume_ratio"] < MIN_VOLUME_RATIO:
            logger.debug(f"[{symbol} {timeframe}m] volume_ratio={prev['volume_ratio']:.2f} — нет объёма, пропуск")
            return None

        patterns = detect_all_patterns(df)
        session_info = get_session_info()

        long_score, long_reasons = _score_long(df, patterns)
        short_score, short_reasons = _score_short(df, patterns)

        # Выбираем направление с максимальным score
        if long_score >= short_score and long_score >= MIN_CONFIDENCE:
            direction = "LONG"
            confidence = min(long_score, 95)
            reasons = long_reasons
        elif short_score > long_score and short_score >= MIN_CONFIDENCE:
            direction = "SHORT"
            confidence = min(short_score, 95)
            reasons = short_reasons
        else:
            return None

        entry = last["close"]
        atr = last["atr"]

        # Стоп-лосс: ATR-based, но не больше MAX_STOP_LOSS_PCT
        sl_atr = atr * 1.5
        sl_max = entry * (MAX_STOP_LOSS_PCT / 100)
        sl_dist = min(sl_atr, sl_max)

        if direction == "LONG":
            stop_loss = entry - sl_dist
            tp1 = entry + sl_dist * TP1_MULTIPLIER
            tp2 = entry + sl_dist * TP2_MULTIPLIER
        else:
            stop_loss = entry + sl_dist
            tp1 = entry - sl_dist * TP1_MULTIPLIER
            tp2 = entry - sl_dist * TP2_MULTIPLIER

        risk_pct = (sl_dist / entry) * 100
        scenarios = _build_scenarios(df, direction, round(tp1, 6), round(tp2, 6), round(stop_loss, 6))
        mtf = get_mtf_analysis(symbol, direction)

        # 3. Конфлюэнция ТФ (Стинбарджер: минимум 2/3 ТФ должны подтверждать)
        if mtf["confluence"] < MIN_MTF_CONFLUENCE:
            logger.debug(
                f"[{symbol} {timeframe}m] confluence={mtf['confluence']}/3 < {MIN_MTF_CONFLUENCE} — "
                f"мало подтверждений ТФ, пропуск"
            )
            return None

        # Расчёт плеча и позиции
        pos = _calc_position(
            entry       = entry,
            stop_loss   = stop_loss,
            confidence  = confidence,
            confluence  = mtf["confluence"],
            adx         = float(last.get("adx", 0)),
            atr_pct     = risk_pct,
        )

        return {
            "symbol":          symbol,
            "timeframe":       f"{timeframe}m",
            "direction":       direction,
            "entry":           round(entry, 6),
            "stop_loss":       round(stop_loss, 6),
            "tp1":             round(tp1, 6),
            "tp2":             round(tp2, 6),
            "risk_pct":        round(risk_pct, 2),
            "confidence":      confidence,
            "reasons":         reasons,
            "scenario_main":   scenarios["scenario_main"],
            "scenario_risk":   scenarios["scenario_risk"],
            "mtf":             mtf,
            "session":         session_info["session"],
            "volatility":      session_info["volatility"],
            "timestamp":       datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
            "rsi":             round(last["rsi"], 1),
            "macd_hist":       round(last["macd_hist"], 6),
            "volume_ratio":    round(last["volume_ratio"], 2),
            # Управление капиталом
            "leverage":        pos["leverage"],
            "lev_why":         pos["lev_why"],
            "position_usd":    pos["position_usd"],
            "margin_usd":      pos["margin_usd"],
            "risk_usd":        pos["risk_usd"],
            "tp1_profit":      pos["tp1_profit"],
            "tp2_profit":      pos["tp2_profit"],
            "sl_loss":         pos["sl_loss"],
            "account_size":    pos["account_size"],
            "risk_pct_account": pos["risk_pct"],
            "pos_warning":     pos["warning"],
        }

    except Exception as e:
        logger.error(f"generate_signal error [{symbol} {timeframe}m]: {e}")
        return None
