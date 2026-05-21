import asyncio
import logging
import threading
import time
from typing import Optional

from config import SYMBOLS, TIMEFRAMES, SCAN_INTERVAL, MIN_CONFIDENCE
from data.fetcher import fetch_ohlcv, get_top_volatile_symbols
from signals.generator import generate_signal
from notifications.telegram_bot import send_signal, send_startup_message, start_polling
from notifications.dashboard import add_signal, run_dashboard
from analytics.tracker import register_signal, start_tracker

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

# Дедупликация: не слать один сигнал дважды в течение 5 минут
_last_signals: dict = {}
_DEDUP_SECONDS = 300


def _is_duplicate(signal: dict) -> bool:
    key = f"{signal['symbol']}_{signal['direction']}"
    now = time.time()
    if now - _last_signals.get(key, 0) < _DEDUP_SECONDS:
        return True
    _last_signals[key] = now
    return False


def _process_pair(symbol: str, tf: str) -> Optional[dict]:
    df = fetch_ohlcv(symbol, tf, limit=200)
    if df.empty:
        return None
    return generate_signal(df, symbol, tf)


async def scan_once():
    loop = asyncio.get_event_loop()

    # Получаем топ-10 самых волатильных монет прямо сейчас
    symbols = await loop.run_in_executor(None, get_top_volatile_symbols, 10)
    logger.info(f"🔍 Сканирование: {', '.join(symbols)}")

    found_count = 0

    for symbol in symbols:
        for tf in TIMEFRAMES:
            try:
                signal = await loop.run_in_executor(None, _process_pair, symbol, tf)

                if signal is None:
                    logger.debug(f"{symbol} {tf}m — нет сигнала")
                    continue

                if _is_duplicate(signal):
                    logger.debug(f"{symbol} {tf}m — дубликат (уже слали < 5 мин)")
                    continue

                logger.info(
                    f"✅ СИГНАЛ: {signal['direction']} {symbol} [{tf}m] "
                    f"conf={signal['confidence']}%"
                )
                send_signal(signal)
                add_signal(signal)
                register_signal(signal)
                found_count += 1

            except Exception as e:
                logger.error(f"Error {symbol} {tf}m: {e}")

    logger.info(f"Готово. Отправлено сигналов: {found_count}")


async def main_loop():
    logger.info("🤖 Crypto Scalping Bot запускается...")
    loop = asyncio.get_event_loop()
    try:
        await asyncio.wait_for(
            loop.run_in_executor(None, lambda: __import__(
                "notifications.telegram_bot", fromlist=["send_text"]
            ).send_text(
                "🤖 *Crypto Scalping Bot запущен*\n"
                "━━━━━━━━━━━━━━━━━━━━\n"
                "📊 Топ-10 волатильных пар с Bybit\n"
                "Команды: /coins /status /stop\n"
                "_Ожидаю сигналы..._"
            )),
            timeout=15
        )
    except Exception:
        pass  # стартовое сообщение не критично — продолжаем
    logger.info("🚀 Бот запущен, начинаю сканирование...")

    while True:
        try:
            await scan_once()
        except Exception as e:
            logger.error(f"Scan loop error: {e}")
        logger.info(f"⏳ Следующее сканирование через {SCAN_INTERVAL} сек...")
        await asyncio.sleep(SCAN_INTERVAL)


if __name__ == "__main__":
    threading.Thread(target=run_dashboard, daemon=True).start()
    logger.info("📊 Дашборд запущен")

    start_polling()
    start_tracker()

    asyncio.run(main_loop())
