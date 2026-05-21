#!/bin/bash
cd "$(dirname "$0")"

if [ -f bot.pid ]; then
    PID=$(cat bot.pid)
    kill "$PID" 2>/dev/null
    rm bot.pid
    echo "⛔ Бот остановлен (PID: $PID)"
else
    # Ищем процесс по имени
    pkill -f "python3 main.py" 2>/dev/null
    echo "⛔ Бот остановлен"
fi

read -p "Нажми Enter чтобы закрыть..."
