from datetime import datetime, timezone
from config import SESSIONS


def get_current_session() -> str:
    """
    Определить текущую торговую сессию по UTC времени.
    Если сессии пересекаются — возвращает более активную (приоритет: NY > London > Asia).
    """
    now_utc = datetime.now(timezone.utc)
    hour = now_utc.hour

    active = []
    for name, times in SESSIONS.items():
        start, end = times["start"], times["end"]
        if start < end:
            if start <= hour < end:
                active.append(name)
        else:
            # переход через полночь
            if hour >= start or hour < end:
                active.append(name)

    priority = ["NY", "London", "Asia"]
    for p in priority:
        if p in active:
            return p

    return "Off-hours"


def get_session_info() -> dict:
    """Вернуть расширенную информацию о сессии."""
    session = get_current_session()
    now_utc = datetime.now(timezone.utc)

    volatility_map = {
        "NY":       "🔴 Высокая",
        "London":   "🟠 Средняя-Высокая",
        "Asia":     "🟡 Средняя",
        "Off-hours":"⚪ Низкая",
    }

    return {
        "session":    session,
        "utc_time":   now_utc.strftime("%H:%M UTC"),
        "volatility": volatility_map.get(session, "⚪ Низкая"),
    }
