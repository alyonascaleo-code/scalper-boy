import json
import os
import threading
import time
import logging
from datetime import datetime, timezone

import pandas as pd

logger = logging.getLogger(__name__)

_DIR = os.path.dirname(os.path.abspath(__file__))
SIGNALS_FILE = os.path.join(_DIR, "signals_log.json")
MONITOR_WINDOW = 7200   # 2 часа — окно мониторинга
CHECK_INTERVAL = 60     # проверять каждую минуту
_lock = threading.Lock()


# ── I/O ──────────────────────────────────────────────────────────────────────

def _load() -> list:
    if not os.path.exists(SIGNALS_FILE):
        return []
    try:
        with open(SIGNALS_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def _save(signals: list):
    with open(SIGNALS_FILE, "w", encoding="utf-8") as f:
        json.dump(signals, f, indent=2, ensure_ascii=False)


# ── Регистрация ───────────────────────────────────────────────────────────────

def register_signal(signal: dict):
    """Записать новый сигнал на отслеживание."""
    now = time.time()
    record = {
        "id":         f"{signal['symbol']}_{signal['direction']}_{int(now)}",
        "symbol":     signal["symbol"],
        "direction":  signal["direction"],
        "timeframe":  signal.get("timeframe", ""),
        "entry":      signal["entry"],
        "stop_loss":  signal["stop_loss"],
        "tp1":        signal["tp1"],
        "tp2":        signal["tp2"],
        "confidence": signal["confidence"],
        "sent_at":    datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "sent_ts":    now,
        "status":     "pending",   # pending | tp1 | tp2 | sl | timeout
        "resolved_at": None,
    }
    with _lock:
        signals = _load()
        signals.append(record)
        _save(signals)
    logger.info(f"Трекер: {record['id']} → отслеживаем 2ч")


# ── Проверка исхода ───────────────────────────────────────────────────────────

def _check_one(record: dict) -> bool:
    """Проверить один сигнал по 1m свечам. Вернуть True если статус изменился."""
    from data.fetcher import fetch_ohlcv

    now = time.time()
    elapsed = now - record["sent_ts"]

    # Таймаут — 2 часа прошли, результата нет
    if elapsed > MONITOR_WINDOW:
        record["status"] = "timeout"
        record["resolved_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        logger.info(f"Трекер: {record['id']} → TIMEOUT (2ч без результата)")
        return True

    try:
        df = fetch_ohlcv(record["symbol"], "1", limit=200)
        if df.empty:
            return False

        # Берём только свечи после момента отправки сигнала
        sent_dt = pd.Timestamp(record["sent_ts"], unit="s")
        df_after = df[df["time"] >= sent_dt]
        if df_after.empty:
            return False

        direction = record["direction"]
        sl  = record["stop_loss"]
        tp1 = record["tp1"]
        tp2 = record["tp2"]

        # Проверяем свеча за свечой (хронологически)
        # Внутри свечи: сначала проверяем SL (консервативно)
        for _, row in df_after.iterrows():
            h, l = row["high"], row["low"]
            if direction == "LONG":
                if l <= sl:
                    record["status"] = "sl";  break
                elif h >= tp2:
                    record["status"] = "tp2"; break
                elif h >= tp1:
                    record["status"] = "tp1"; break
            else:  # SHORT
                if h >= sl:
                    record["status"] = "sl";  break
                elif l <= tp2:
                    record["status"] = "tp2"; break
                elif l <= tp1:
                    record["status"] = "tp1"; break

        if record["status"] != "pending":
            record["resolved_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
            emoji = {"tp1": "✅", "tp2": "🏆", "sl": "❌"}.get(record["status"], "")
            logger.info(f"Трекер: {record['id']} → {emoji} {record['status'].upper()}")
            return True

    except Exception as e:
        logger.error(f"Трекер check error [{record['symbol']}]: {e}")

    return False


def check_pending():
    with _lock:
        signals = _load()
        changed = False
        for r in signals:
            if r["status"] == "pending":
                if _check_one(r):
                    changed = True
        if changed:
            _save(signals)


# ── Статистика ────────────────────────────────────────────────────────────────

def get_stats() -> dict:
    with _lock:
        signals = _load()

    tp1    = sum(1 for s in signals if s["status"] == "tp1")
    tp2    = sum(1 for s in signals if s["status"] == "tp2")
    sl     = sum(1 for s in signals if s["status"] == "sl")
    timeout = sum(1 for s in signals if s["status"] == "timeout")
    pending = sum(1 for s in signals if s["status"] == "pending")

    wins     = tp1 + tp2
    resolved = wins + sl
    win_rate = round(wins / resolved * 100, 1) if resolved > 0 else 0

    return {
        "total":    len(signals),
        "pending":  pending,
        "tp1":      tp1,
        "tp2":      tp2,
        "sl":       sl,
        "timeout":  timeout,
        "wins":     wins,
        "resolved": resolved,
        "win_rate": win_rate,
        "recent":   sorted(signals, key=lambda x: x["sent_ts"], reverse=True)[:30],
    }


# ── Фоновый поток ─────────────────────────────────────────────────────────────

def _loop():
    while True:
        try:
            check_pending()
        except Exception as e:
            logger.error(f"Tracker loop error: {e}")
        time.sleep(CHECK_INTERVAL)


def start_tracker():
    os.makedirs(_DIR, exist_ok=True)
    threading.Thread(target=_loop, daemon=True).start()
    logger.info("📈 Signal tracker запущен — мониторинг 2ч на сигнал")
