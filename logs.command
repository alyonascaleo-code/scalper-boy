#!/bin/bash
cd "$(dirname "$0")"

if [ ! -f bot.log ]; then
    echo "Лог пустой — бот ещё не запускался"
    read -p "Enter..."
    exit
fi

echo "📄 Последние 50 строк лога:"
echo "================================"
tail -50 bot.log
echo "================================"
read -p "Нажми Enter чтобы закрыть..."
