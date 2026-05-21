#!/bin/bash
cd "$(dirname "$0")"

echo "🤖 Запуск Crypto Scalping Bot..."

# Убиваем старый процесс если есть
if [ -f bot.pid ]; then
    OLD_PID=$(cat bot.pid)
    kill "$OLD_PID" 2>/dev/null
    rm bot.pid
    echo "⛔ Старый процесс остановлен"
fi

# Чистим кэш Python
find . -name "*.pyc" -delete 2>/dev/null
find . -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null
echo "🧹 Кэш очищен"

# Запускаем бот в фоне, логи пишем в файл
nohup python3 main.py >> bot.log 2>&1 &
echo $! > bot.pid

echo "✅ Бот запущен! PID: $(cat bot.pid)"
echo "📄 Логи: $(pwd)/bot.log"
echo ""
echo "Чтобы остановить — запусти stop.command"
echo ""
read -p "Нажми Enter чтобы закрыть это окно..."
