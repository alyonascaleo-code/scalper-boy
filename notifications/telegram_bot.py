import logging
import threading
import time
import requests
from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

logger = logging.getLogger(__name__)

TELEGRAM_API = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"

_allowed_chats: set = {str(TELEGRAM_CHAT_ID)} if TELEGRAM_CHAT_ID else set()
_polling_offset: int = 0
_lock = threading.Lock()


# ── Низкоуровневые отправки ───────────────────────────────────────────────────

def _send_to(chat_id: str, text: str, parse_mode: str = "Markdown") -> bool:
    try:
        resp = requests.post(
            f"{TELEGRAM_API}/sendMessage",
            json={"chat_id": chat_id, "text": text, "parse_mode": parse_mode},
            timeout=10,
        )
        if not resp.ok:
            err_body = resp.text[:300]
            logger.error(f"Telegram {resp.status_code} → {err_body}")
            # Если ошибка Markdown — шлём без форматирования
            if resp.status_code == 400 and "parse" in err_body.lower():
                logger.warning("Повтор без Markdown...")
                resp2 = requests.post(
                    f"{TELEGRAM_API}/sendMessage",
                    json={"chat_id": chat_id, "text": text},
                    timeout=10,
                )
                return resp2.ok
            return False
        return True
    except Exception as e:
        logger.error(f"Send error to {chat_id}: {e}")
        return False


def _send_inline(chat_id: str, text: str, keyboard: list, parse_mode: str = "Markdown") -> dict:
    """Отправить сообщение с inline-кнопками."""
    try:
        resp = requests.post(
            f"{TELEGRAM_API}/sendMessage",
            json={
                "chat_id": chat_id,
                "text": text,
                "parse_mode": parse_mode,
                "reply_markup": {"inline_keyboard": keyboard},
            },
            timeout=10,
        )
        return resp.json()
    except Exception as e:
        logger.error(f"Send inline error: {e}")
        return {}


def _edit_message(chat_id: str, message_id: int, text: str,
                  keyboard: list = None, parse_mode: str = "Markdown"):
    """Обновить существующее сообщение на месте."""
    payload = {
        "chat_id": chat_id,
        "message_id": message_id,
        "text": text,
        "parse_mode": parse_mode,
    }
    if keyboard is not None:
        payload["reply_markup"] = {"inline_keyboard": keyboard}
    try:
        requests.post(f"{TELEGRAM_API}/editMessageText", json=payload, timeout=10)
    except Exception as e:
        logger.error(f"Edit message error: {e}")


def _answer_callback(callback_id: str, text: str = ""):
    try:
        requests.post(
            f"{TELEGRAM_API}/answerCallbackQuery",
            json={"callback_query_id": callback_id, "text": text},
            timeout=5,
        )
    except Exception:
        pass


def _send_request(text: str, parse_mode: str = "Markdown") -> bool:
    if not TELEGRAM_BOT_TOKEN:
        return False
    ok = False
    with _lock:
        chats = set(_allowed_chats)
    for chat_id in chats:
        if _send_to(chat_id, text, parse_mode):
            ok = True
    return ok


# ── Клавиатуры ────────────────────────────────────────────────────────────────

def _coins_keyboard() -> list:
    """Inline-клавиатура с кнопками по каждой монете."""
    try:
        from analytics.tracker import get_stats
        perf = get_stats()
        coins = sorted(set(r["symbol"] for r in perf["recent"]))
    except Exception:
        coins = []

    if not coins:
        from config import SYMBOLS
        coins = SYMBOLS

    rows = []
    row = []
    for coin in coins:
        label = coin.replace("USDT", "")
        row.append({"text": label, "callback_data": f"coin:{coin}"})
        if len(row) == 3:
            rows.append(row)
            row = []
    if row:
        rows.append(row)

    rows.append([{"text": "📊 Общая статистика", "callback_data": "coin:ALL"}])
    return rows


# ── Форматирование статистики по монете ───────────────────────────────────────

def _format_coin_stats(symbol: str) -> str:
    try:
        from analytics.tracker import get_stats
        perf = get_stats()
    except Exception:
        return f"*{symbol}*\n\nОшибка загрузки данных."

    if symbol == "ALL":
        records = perf["recent"]
        title = "📊 *Общая статистика*"
    else:
        records = [r for r in perf["recent"] if r["symbol"] == symbol]
        title = f"📊 *{symbol}*"

    if not records:
        return f"{title}\n\nПока нет сигналов. Жди следующего скана."

    tp1     = sum(1 for r in records if r["status"] == "tp1")
    tp2     = sum(1 for r in records if r["status"] == "tp2")
    sl      = sum(1 for r in records if r["status"] == "sl")
    pending = sum(1 for r in records if r["status"] == "pending")
    timeout = sum(1 for r in records if r["status"] == "timeout")
    wins    = tp1 + tp2
    resolved = wins + sl
    win_rate = round(wins / resolved * 100, 1) if resolved > 0 else 0

    wr_bar = "🟩" * int(win_rate / 10) + "⬜" * (10 - int(win_rate / 10))

    # Последние 5 сигналов
    recent_lines = []
    for r in records[:5]:
        s_emoji = {"tp2": "🏆", "tp1": "✅", "sl": "❌", "pending": "⏳", "timeout": "⌛"}.get(r["status"], "❓")
        d_emoji = "🟢" if r["direction"] == "LONG" else "🔴"
        recent_lines.append(
            f"  {s_emoji} {d_emoji} {r['direction']} {r['confidence']}% → {r['sent_at']}"
        )
    recent_text = "\n".join(recent_lines)

    return (
        f"{title}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"{wr_bar}\n"
        f"🎯 *Win Rate: {win_rate}%* ({resolved} завершённых)\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🏆 TP2: {tp2}   ✅ TP1: {tp1}   ❌ SL: {sl}\n"
        f"⏳ Ожидаем: {pending}   ⌛ Таймаут: {timeout}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"*Последние сигналы:*\n{recent_text}"
    )


# ── Обработка обновлений ──────────────────────────────────────────────────────

def _handle_update(update: dict):
    global _polling_offset
    _polling_offset = update["update_id"] + 1

    # ── Callback query (нажатие кнопки) ──
    callback = update.get("callback_query", {})
    if callback:
        cb_id      = callback["id"]
        data       = callback.get("data", "")
        cb_chat_id = str(callback.get("from", {}).get("id", ""))
        msg        = callback.get("message", {})
        msg_id     = msg.get("message_id")

        _answer_callback(cb_id)

        if data.startswith("coin:"):
            symbol = data.replace("coin:", "")
            text   = _format_coin_stats(symbol)
            back   = [[{"text": "◀ Все монеты", "callback_data": "show_coins"}]]
            if msg_id:
                _edit_message(cb_chat_id, msg_id, text, back)
            else:
                _send_inline(cb_chat_id, text, back)

        elif data == "show_coins":
            kb   = _coins_keyboard()
            text = "📊 *Выбери монету:*"
            if msg_id:
                _edit_message(cb_chat_id, msg_id, text, kb)
            else:
                _send_inline(cb_chat_id, text, kb)
        return

    # ── Обычные команды ──
    message    = update.get("message", {})
    text       = message.get("text", "").strip()
    chat       = message.get("chat", {})
    chat_id    = str(chat.get("id", ""))
    first_name = message.get("from", {}).get("first_name", "Трейдер")

    if not chat_id:
        return

    if text == "/start":
        with _lock:
            _allowed_chats.add(chat_id)
        from config import SYMBOLS, TIMEFRAMES, MIN_CONFIDENCE
        pairs = ", ".join(SYMBOLS[:4]) + "..."
        tfs   = "m, ".join(TIMEFRAMES) + "m"
        _send_to(chat_id, (
            f"🤖 *Привет, {first_name}!*\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"Ты подключён к *Crypto Scalping Bot*\n\n"
            f"📊 Топ волатильных пар с Bybit\n"
            f"⏱ Таймфреймы: {tfs}\n"
            f"🎯 Мин. уверенность: {MIN_CONFIDENCE}%\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"*Команды:*\n"
            f"/coins — статистика по каждой монете\n"
            f"/status — состояние бота\n"
            f"/stop — остановить сигналы"
        ))
        logger.info(f"Chat {chat_id} ({first_name}) подписался")

    elif text == "/stop":
        with _lock:
            _allowed_chats.discard(chat_id)
        _send_to(chat_id, f"⛔ *{first_name}, сигналы остановлены*\n\n/start — возобновить")
        logger.info(f"Chat {chat_id} ({first_name}) отписался")

    elif text == "/status":
        from config import MIN_CONFIDENCE, TIMEFRAMES
        try:
            from analytics.tracker import get_stats
            perf = get_stats()
            wr   = perf["win_rate"]
            res  = perf["resolved"]
        except Exception:
            wr, res = 0, 0
        with _lock:
            active = len(_allowed_chats)
        _send_to(chat_id, (
            f"📡 *Статус бота*\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"✅ Работает\n"
            f"👥 Подписчиков: {active}\n"
            f"🎯 Порог: {MIN_CONFIDENCE}%\n"
            f"📊 Win Rate: {wr}% ({res} сигналов)\n"
            f"⏱ ТФ: {', '.join(TIMEFRAMES)}m\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"/coins — статистика по монетам"
        ))

    elif text == "/coins":
        kb = _coins_keyboard()
        if kb:
            _send_inline(chat_id, "📊 *Выбери монету для статистики:*", kb)
        else:
            _send_to(chat_id, "Пока нет данных. Дождись первых сигналов.")


# ── Polling ───────────────────────────────────────────────────────────────────

def polling_loop():
    global _polling_offset
    if TELEGRAM_CHAT_ID:
        with _lock:
            _allowed_chats.add(str(TELEGRAM_CHAT_ID))
    logger.info("📡 Telegram polling запущен — слушаю /start /stop /status /coins")
    while True:
        try:
            resp = requests.get(
                f"{TELEGRAM_API}/getUpdates",
                params={"timeout": 20, "offset": _polling_offset},
                timeout=25,
            )
            if resp.ok:
                for update in resp.json().get("result", []):
                    try:
                        _handle_update(update)
                    except Exception as e:
                        logger.error(f"Handle update error: {e}")
        except Exception as e:
            logger.error(f"Polling error: {e}")
            time.sleep(5)


def start_polling():
    threading.Thread(target=polling_loop, daemon=True).start()


# ── Форматирование сигнала ────────────────────────────────────────────────────

def _format_signal(signal: dict) -> str:
    direction_emoji = "🟢" if signal["direction"] == "LONG" else "🔴"
    conf     = signal["confidence"]
    conf_bar = "🔥" if conf >= 80 else ("⚡" if conf >= 70 else "✅")

    all_patterns  = [r for r in signal["reasons"] if r.startswith("Паттерн:")]
    other_reasons = [r for r in signal["reasons"] if not r.startswith("Паттерн:")]
    reasons_text  = "\n".join(f"  • {r}" for r in other_reasons[:5])

    sc_main = signal.get("scenario_main", {})
    sc_risk = signal.get("scenario_risk", {})
    sc_main_text = "\n".join(f"  • {p}" for p in sc_main.get("points", []))
    sc_risk_text = "\n".join(f"  • {p}" for p in sc_risk.get("points", []))

    mtf          = signal.get("mtf", {})
    tf_data      = mtf.get("timeframes", {})
    confluence   = mtf.get("confluence", 0)
    entry_window = mtf.get("entry_window", "")
    entry_minutes = mtf.get("entry_minutes", "")
    signal_dir   = signal["direction"]

    def tf_line(label: str) -> str:
        d = tf_data.get(label)
        if not d:
            return f"  • {label}: нет данных"
        trend    = d["trend"]
        confirms = d.get("confirms", 0)
        if trend == signal_dir:
            trend_icon = "✅"
            trend_word = f"подтверждает {signal_dir} ({confirms}/4)"
        elif trend == "AGAINST":
            trend_icon = "❌"
            trend_word = f"против {signal_dir} ({confirms}/4)"
        else:
            trend_icon = "🟡"
            trend_word = f"нейтральный ({confirms}/4)"
        vol_info = f" | Объём ×{d['volume_ratio']}" if d["volume_ratio"] > 1.3 else ""
        return f"  • *{label}:* {trend_icon} {trend_word} | RSI {d['rsi']} | MACD {d['macd_label']}{vol_info}"

    mtf_block      = "\n".join(tf_line(lbl) for lbl in ["1m", "5m", "15m"])
    confluence_str = f"{'⭐' * confluence}{'☆' * (3 - confluence)} ({confluence}/3 ТФ)"

    # Блок управления капиталом
    leverage     = signal.get("leverage", "—")
    position_usd = signal.get("position_usd", "—")
    margin_usd   = signal.get("margin_usd", "—")
    lev_why      = signal.get("lev_why", "")
    pos_warning  = signal.get("pos_warning", "")
    account_size = signal.get("account_size", 100)
    tp1_profit   = signal.get("tp1_profit", "—")
    tp2_profit   = signal.get("tp2_profit", "—")
    sl_loss      = signal.get("sl_loss", "—")

    money_block = (
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"💰 *Управление капиталом:*\n"
        f"  Плечо: *{leverage}x*  |  Депозит: *${account_size:.0f}*\n"
        f"  Позиция: *${position_usd}*  |  Маржа: *${margin_usd}*\n"
        f"  _{lev_why}_\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📈 *Профит если сработает:*\n"
        f"  🎯 TP1 → *+${tp1_profit}*\n"
        f"  🏆 TP2 → *+${tp2_profit}*\n"
        f"  ❌ Стоп-лосс → *-${sl_loss}*\n"
        + (f"  {pos_warning}\n" if pos_warning else "")
    )

    return (
        f"{direction_emoji} *{signal['direction']} {signal['symbol']}* "
        f"[{signal['timeframe']}]\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📍 *Вход:* `{signal['entry']}`\n"
        f"🛑 *Стоп:* `{signal['stop_loss']}` (-{signal['risk_pct']}%)\n"
        f"🎯 *TP1:*  `{signal['tp1']}`\n"
        f"🎯 *TP2:*  `{signal['tp2']}`\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"{conf_bar} *Уверенность:* {conf}% | {confluence_str}\n"
        f"🕐 *Сессия:* {signal['session']} {signal['volatility']}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📊 *Анализ таймфреймов:*\n{mtf_block}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"⏰ *Когда входить:*\n"
        f"  {entry_window}\n"
        f"  _{entry_minutes}_\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📋 *Индикаторы:*\n{reasons_text}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🔍 *Паттерны:*\n" +
        ("\n".join(f"  {r.replace('Паттерн: ','')}" for r in all_patterns)
         if all_patterns else "  • нет совпадений") +
        f"\n━━━━━━━━━━━━━━━━━━━━\n"
        f"*{sc_main.get('title', '')}*\n{sc_main_text}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"*{sc_risk.get('title', '')}*\n{sc_risk_text}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🕒 {signal['timestamp']}\n"
        + money_block
    )


def send_signal(signal: dict) -> bool:
    from config import MIN_CONFIDENCE
    if signal.get("confidence", 0) < MIN_CONFIDENCE:
        return False
    try:
        text = _format_signal(signal)
        ok = _send_request(text)
        if ok:
            logger.info(f"📨 Telegram OK: {signal['direction']} {signal['symbol']} [{signal['timeframe']}]")
        else:
            logger.warning(f"📨 Telegram FAILED: {signal['direction']} {signal['symbol']} [{signal['timeframe']}]")
        return ok
    except Exception as e:
        logger.error(f"send_signal format error: {e}", exc_info=True)
        return False


def send_text(message: str) -> bool:
    return _send_request(message)


async def send_startup_message() -> None:
    from config import TIMEFRAMES, MIN_CONFIDENCE
    tf_str = "m, ".join(TIMEFRAMES) + "m"
    _send_request(
        "🤖 *Crypto Scalping Bot запущен*\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "📊 Топ-10 волатильных пар с Bybit\n"
        f"⏱ Таймфреймы: {tf_str}\n"
        f"🎯 Мин. уверенность: {MIN_CONFIDENCE}%\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "Команды: /coins /status /stop\n"
        "_Ожидаю сигналы..._"
    )
