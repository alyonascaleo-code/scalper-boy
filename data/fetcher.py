import time
import socket
import logging
import concurrent.futures
import pandas as pd
from pybit.unified_trading import HTTP
from config import BYBIT_API_KEY, BYBIT_API_SECRET, BYBIT_TESTNET

logger = logging.getLogger(__name__)

_last_connectivity_alert = 0   # чтобы не спамить уведомлениями

# ── DNS-фолбэк: если системный DNS не резолвит api.bybit.com ──────────────────
_BYBIT_HOST = "api.bybit.com"
_BYBIT_FALLBACK_IPS = ["99.86.20.16", "99.86.20.8"]   # CloudFront IPs из nslookup
_resolved_bybit_ip: str = ""
_original_getaddrinfo = socket.getaddrinfo
_dns_pool = concurrent.futures.ThreadPoolExecutor(max_workers=2, thread_name_prefix="dns")


def _resolve_bybit_ip() -> str:
    """Резолвим api.bybit.com через Google DNS (без зависания)."""
    try:
        import dns.resolver
        resolver = dns.resolver.Resolver()
        resolver.nameservers = ["8.8.8.8"]
        resolver.timeout = 3
        resolver.lifetime = 3
        answers = resolver.resolve(_BYBIT_HOST, "A")
        ip = str(answers[0])
        logger.info(f"DNS-фолбэк: {_BYBIT_HOST} → {ip} (Google DNS)")
        return ip
    except Exception:
        logger.warning(f"Google DNS тоже недоступен — используем хардкод {_BYBIT_FALLBACK_IPS[0]}")
        return _BYBIT_FALLBACK_IPS[0]


def _getaddrinfo_with_fallback(host, port, *args, **kwargs):
    """Перехватываем dns-запрос к api.bybit.com и ставим таймаут 3 сек."""
    global _resolved_bybit_ip
    if host != _BYBIT_HOST:
        return _original_getaddrinfo(host, port, *args, **kwargs)

    # Пробуем системный DNS с таймаутом 3 сек (не висим!)
    try:
        future = _dns_pool.submit(_original_getaddrinfo, host, port, *args, **kwargs)
        return future.result(timeout=3)
    except Exception:
        pass  # системный DNS завис или ошибка — берём фолбэк

    if not _resolved_bybit_ip:
        _resolved_bybit_ip = _resolve_bybit_ip()

    return _original_getaddrinfo(_resolved_bybit_ip, port, *args, **kwargs)


socket.getaddrinfo = _getaddrinfo_with_fallback


def get_client() -> HTTP:
    return HTTP(
        testnet=BYBIT_TESTNET,
        api_key=BYBIT_API_KEY,
        api_secret=BYBIT_API_SECRET,
        timeout=8,          # макс. 8 сек на запрос (дефолт pybit ~60 сек)
        recv_window=5000,
    )


def _retry(fn, retries: int = 3, delay: float = 5.0):
    """Выполнить функцию с повторными попытками при сетевых ошибках."""
    global _last_connectivity_alert
    for attempt in range(retries):
        try:
            return fn()
        except Exception as e:
            err = str(e)
            is_network = any(x in err for x in ["NameResolution", "ConnectionError",
                                                  "Max retries", "RemoteDisconnected",
                                                  "TimeoutError", "ConnectTimeout"])
            if is_network:
                if attempt < retries - 1:
                    logger.warning(f"Сетевая ошибка (попытка {attempt+1}/{retries}), жду {delay}с: {err[:80]}")
                    time.sleep(delay)
                else:
                    # Последняя попытка провалилась — уведомляем раз в 10 минут
                    now = time.time()
                    if now - _last_connectivity_alert > 600:
                        _last_connectivity_alert = now
                        try:
                            from notifications.telegram_bot import send_text
                            send_text("⚠️ *Бот потерял связь с Bybit*\nПроверь интернет-соединение. Автоматически восстановлюсь как только появится связь.")
                        except Exception:
                            pass
                    raise
            else:
                raise
    return None


def fetch_ohlcv(symbol: str, interval: str, limit: int = 200) -> pd.DataFrame:  # noqa: E302
    """
    Получить OHLCV данные с Bybit.

    :param symbol:   торговая пара, напр. 'BTCUSDT'
    :param interval: таймфрейм в минутах ('1' или '5')
    :param limit:    количество свечей (макс 200)
    :return:         DataFrame с колонками [time, open, high, low, close, volume]
    """
    def _fetch():
        client = get_client()
        resp = client.get_kline(
            category="linear",
            symbol=symbol,
            interval=interval,
            limit=limit,
        )
        raw = resp["result"]["list"]
        df = pd.DataFrame(raw, columns=[
            "time", "open", "high", "low", "close", "volume", "turnover"
        ])
        df = df.astype({
            "time":     "int64",
            "open":     "float64",
            "high":     "float64",
            "low":      "float64",
            "close":    "float64",
            "volume":   "float64",
            "turnover": "float64",
        })
        df = df.sort_values("time").reset_index(drop=True)
        df["time"] = pd.to_datetime(df["time"], unit="ms")
        return df[["time", "open", "high", "low", "close", "volume"]]

    try:
        return _retry(_fetch, retries=3, delay=5.0)
    except Exception as e:
        logger.error(f"fetch_ohlcv error [{symbol} {interval}m]: {e}")
        return pd.DataFrame()


def fetch_orderbook(symbol: str, limit: int = 25) -> dict:
    """Получить стакан ордеров (для Фазы 2)."""
    client = get_client()
    try:
        resp = client.get_orderbook(
            category="linear",
            symbol=symbol,
            limit=limit,
        )
        return resp["result"]
    except Exception as e:
        logger.error(f"fetch_orderbook error [{symbol}]: {e}")
        return {}


def fetch_ticker(symbol: str) -> dict:
    """Получить текущую цену и объём за 24ч."""
    client = get_client()
    try:
        resp = client.get_tickers(category="linear", symbol=symbol)
        return resp["result"]["list"][0]
    except Exception as e:
        logger.error(f"fetch_ticker error [{symbol}]: {e}")
        return {}


def get_top_volatile_symbols(top_n: int = 10, min_turnover_usd: float = 50_000_000) -> list:
    """
    Получить топ-N самых волатильных USDT-перп монет с Bybit.
    Критерии: |изменение за 24ч %| × объём — самые горячие монеты прямо сейчас.
    min_turnover_usd — минимальный оборот за 24ч в USD (отсекает неликвид).
    """
    def _fetch_tickers():
        client = get_client()
        return client.get_tickers(category="linear")["result"]["list"]

    try:
        tickers = _retry(_fetch_tickers, retries=3, delay=5.0)

        candidates = []
        for t in tickers:
            sym = t.get("symbol", "")
            # Только USDT бессрочные, без индексов/опционов
            if not sym.endswith("USDT") or sym.startswith("1000"):
                continue

            try:
                change_pct = abs(float(t.get("price24hPcnt", 0))) * 100  # e.g. 5.23
                turnover   = float(t.get("turnover24h", 0))
                price      = float(t.get("lastPrice", 0))
            except (ValueError, TypeError):
                continue

            # Фильтр ликвидности — отсекаем мелочь
            if turnover < min_turnover_usd or price < 0.0001:
                continue

            # Скор: волатильность × логарифм объёма (чтобы объём не перебивал всё)
            import math
            score = change_pct * math.log10(max(turnover, 1))
            candidates.append((score, change_pct, turnover, sym))

        # Сортируем по скору — топ волатильных с хорошим объёмом
        candidates.sort(reverse=True)
        symbols = [sym for _, _, _, sym in candidates[:top_n]]

        logger.info(
            f"Топ-{top_n} волатильных монет: " +
            ", ".join(
                f"{sym}({chg:.1f}%)"
                for _, chg, _, sym in candidates[:top_n]
            )
        )
        return symbols

    except Exception as e:
        logger.error(f"get_top_volatile_symbols error: {e}")
        # Фолбэк на стандартный список
        from config import SYMBOLS
        return SYMBOLS
