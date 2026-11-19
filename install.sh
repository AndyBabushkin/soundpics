#!/usr/bin/env bash
# Установка SoundPics на Ubuntu (22.04 / 24.04 / 26.04, PipeWire).
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="$HOME/.local/share/soundpics-venv"

echo "==> Установка системных зависимостей (нужен sudo)…"
sudo apt-get update
sudo apt-get install -y --no-install-recommends \
    ffmpeg python3-venv python3-tk pulseaudio-utils pipewire-bin

echo "==> Создаю virtualenv $VENV …"
python3 -m venv "$VENV"
"$VENV/bin/pip" install --upgrade pip
"$VENV/bin/pip" install -r "$APP_DIR/requirements.txt"

echo "==> Добавляю ярлык в меню приложений…"
mkdir -p "$HOME/.local/share/applications"
sed "s#@VENV@#$VENV#g; s#@APP_DIR@#$APP_DIR#g" \
    "$APP_DIR/soundpics.desktop" \
    > "$HOME/.local/share/applications/soundpics.desktop"

echo
echo "Готово! При первом запуске Whisper скачает модель (small ≈ 1 ГБ)."
echo "Запуск:  $VENV/bin/python3 $APP_DIR/run.py"
echo "Или найдите SoundPics в меню приложений."
echo "Проверка без аудио:  $VENV/bin/python3 $APP_DIR/run.py --dry-run"
