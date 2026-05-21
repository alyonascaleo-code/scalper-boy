import os
from dotenv import load_dotenv

load_dotenv()

# === BYBIT API ===
BYBIT_API_KEY = os.getenv("BYBIT_API_KEY", "")
BYBIT_API_SECRET = os.getenv("BYBIT_API_SECRET", "")
BYBIT_TESTNET = os.getenv("BYBIT_TESTNET", "false").lower() == "true"

# === TELEGRAM ===
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# === ТОРГОВЫЕ ПАРЫ ===
SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "DOGEUSDT", "AVAXUSDT", "LINKUSDT"]

# === ТАЙМФРЕЙМЫ ===
TIMEFRAMES = ["1", "5", "15"]  # минуты (Bybit формат)

# === ПАРАМЕТРЫ СИГНАЛОВ ===
MIN_CONFIDENCE = 60        # минимальная уверенность % (Стинбарджер: только чёткие сетапы)
MAX_STOP_LOSS_PCT = 2.0    # максимальный стоп-лосс %
TP1_MULTIPLIER = 2.0       # TP1 = риск × 2
TP2_MULTIPLIER = 3.0       # TP2 = риск × 3

# === ФИЛЬТРЫ СТИНБАРДЖЕРА ===
MIN_ADX = 20               # минимальный ADX — торгуем только тренд, не боковик
MIN_VOLUME_RATIO = 1.1     # объём должен быть выше среднего — подтверждение входа
MIN_MTF_CONFLUENCE = 2     # минимум 2 из 3 ТФ должны подтверждать направление

# === ИНДИКАТОРЫ ===
RSI_PERIOD = 14
RSI_OVERSOLD = 30
RSI_OVERBOUGHT = 70

EMA_FAST = 9
EMA_SLOW = 21
EMA_TREND = 50

MACD_FAST = 12
MACD_SLOW = 26
MACD_SIGNAL = 9

BB_PERIOD = 20
BB_STD = 2.0

ATR_PERIOD = 14
VOLUME_MA_PERIOD = 20

# === СЕССИИ (UTC) ===
SESSIONS = {
    "Asia":   {"start": 0,  "end": 8},
    "London": {"start": 7,  "end": 16},
    "NY":     {"start": 13, "end": 22},
}

# === ДАШБОРД ===
DASHBOARD_HOST = os.getenv("DASHBOARD_HOST", "0.0.0.0")
DASHBOARD_PORT = int(os.getenv("DASHBOARD_PORT", 5000))
DASHBOARD_DEBUG = os.getenv("DASHBOARD_DEBUG", "false").lower() == "true"

# === УПРАВЛЕНИЕ КАПИТАЛОМ ===
ACCOUNT_SIZE       = float(os.getenv("ACCOUNT_SIZE", 1000))   # депозит в USD
RISK_PER_TRADE_PCT = float(os.getenv("RISK_PER_TRADE_PCT", 1.5))  # риск на сделку % от депозита

# === ИНТЕРВАЛ СКАНИРОВАНИЯ (секунды) ===
SCAN_INTERVAL = 120          # сканировать каждые 2 минуты
DIGEST_INTERVAL = 300        # лучший сигнал по каждой монете каждые 5 минут
