# SoundPics 🎨🔊

Приложение для Ubuntu, которое **слушает звук, воспроизводимый на устройстве**, распознаёт речь
и в отдельном окне показывает **по картинке на каждые 2–3 значимых слова** (из бесплатных
источников без ключей: Openverse и Wikimedia Commons).

Работает с любым звуком: YouTube, фильмы, подкасты, музыка с вокалом, звонки —
capture идёт через monitor-источник системного вывода PipeWire/PulseAudio.

```
┌──────────────┐   ┌──────────────┐   ┌──────────────┐   ┌──────────────┐
│ системный    │   │ faster-      │   │ значимые     │   │ Openverse /  │
│ звук →       │→  │ whisper      │→  │ слова по     │→  │ Wikimedia →  │
│ monitor      │   │ (локально)   │   │ 2–3 слова    │   │ картинка     │
└──────────────┘   └──────────────┘   └──────────────┘   └──────────────┘
```

## Установка (Ubuntu 22.04 / 24.04 / 26.04)

```bash
cd soundpics
./install.sh
```

Скрипт ставит системные пакеты (`ffmpeg`, `python3-tk`, `pulseaudio-utils`, `pipewire-bin`),
создаёт virtualenv в `~/.local/share/soundpics-venv`, ставит Python-зависимости и добавляет
ярлык в меню приложений.

Требования: Ubuntu с PipeWire (по умолчанию с 22.04), Python 3.11+.

## Запуск

- из меню приложений (SoundPics) или
- вручную: `~/.local/share/soundpics-venv/bin/python3 ~/soundpics/run.py`

При первом запуске faster-whisper скачает модель (~150 МБ для `tiny`, ~300 МБ для `base`,
~1 ГБ для `small`) — нужен интернет, потом работает офлайн.

## Проверка без наушников/микрофона

```bash
# прогнать встроенный пример текста через весь конвейер (печатает запросы и качает картинки)
~/.local/share/soundpics-venv/bin/python3 run.py --dry-run

# то же со своим текстом
~/.local/share/soundpics-venv/bin/python3 run.py --dry-run --text examples/sample_ru.txt

# проверить поиск картинки по одному запросу
~/.local/share/soundpics-venv/bin/python3 run.py --test-image "старый город"

# посмотреть доступные monitor-источники
~/.local/share/soundpics-venv/bin/python3 run.py --list-devices
```

## Настройка (`config.toml` рядом с `run.py`)

| Раздел | Параметр | Смысл |
|---|---|---|
| `[audio]` | `backend` | `auto` \| `parecord` \| `ffmpeg` \| `pw-record` |
| | `device` | имя monitor-источника; пусто = автовыбор |
| | `chunk_seconds` | длина куска аудио для распознавания (меньше → отзывчивее) |
| `[stt]` | `model` | `tiny` \| `base` \| `small` \| `medium` |
| | `language` | `ru` \| `en` \| `""` (авто) |
| | `device` | `cpu` \| `cuda` (если есть GPU) |
| `[words]` | `trigger` | сколько значимых слов копить до запроса (по умолчанию 2) |
| | `max_per_query` | максимум слов в запросе (3) |
| | `min_interval` | пауза между поисками картинок, сек (4) |
| `[images]` | `providers` | порядок источников: `openverse`, `wikimedia` |
| | `cache_dir` | папка кэша картинок |
| | `prefer` | `random` \| `first` |
| `[ui]` | `always_on_top`, `width`, `height`, `fullscreen` | окно |

CLI перекрывает конфиг: `--model tiny --language en --chunk 2 --trigger 3 --interval 6`.

## Горячие клавиши в окне

- `Q` / `Esc` — выход
- `F` — полный экран
- `T` — режим «поверх всех окон»

## Решение проблем

- **Нет захвата звука / приложение молчит.** Запустите `--list-devices`. Если список пуст —
  установите `pulseaudio-utils` или `pipewire-bin` (`sudo apt install pulseaudio-utils`).
  Убедитесь, что звук вообще играет (monitor существует только для активного вывода).
  Можно явно указать устройство: `run.py --device alsa_output.pci-....monitor`.
- **Плохо понимает русский.** Возьмите `model = "small"` или `medium`; `tiny` часто путается.
  Для англоязычного контента — `language = "en"`.
- **Картинки находятся медленно / не находятся.** Поднимьте `min_interval` (например, 6–8 с),
  чтобы не упираться в лимиты Openverse. Проверьте интернет: `--test-image кот`.
- **Ошибка «Не найдено средство захвата звука».** Поставьте `ffmpeg` или `pulseaudio-utils`,
  либо переключите `backend` в конфиге.
- **Всё тормозит на CPU.** `model = "tiny"`, `chunk_seconds = 2.5`. Есть GPU — `device = "cuda"`.
- **Wayland.** Захват monitor-источника работает и в Wayland: мы читаем звуковой graph
  PipeWire, а не картинку экрана.

## Приватность

Распознавание речи — полностью локально (Whisper на вашем CPU). В интернет уходит только
текст поискового запроса (2–3 слова) к Openverse/Wikimedia, когда ищем картинку.

## Идеи доработки (если захочется)

- Google Custom Search API как ещё один провайдер (нужны бесплатные ключ и CX);
- локальный кэш «слово → картинка» с выбором лучшего кадра;
- субтитры поверх картинки; история показанного;
- VOSK как потоковый распознаватель с word-level результатами (мгновенные обновления).
