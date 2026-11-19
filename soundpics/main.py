"""Точка входа SoundPics.

Схема работы:
  захват системного звука → распознавание (faster-whisper) →
  значимые слова → поиск картинки (Openverse/Wikimedia) → окно Tkinter.
"""
from __future__ import annotations

import argparse
import logging
import queue
import re
import threading
import time
from pathlib import Path

from .audio import AudioCapture, list_monitors, list_monitors_pw, put_dropold, resolve
from .config import load_config
from .gui import ImageWindow
from .images import ImageProvider
from .keywords import KeywordExtractor

log = logging.getLogger("soundpics")

DEMO_TEXT = (
    "Представь себе старый город у моря, где узкие улочки пахнут кофе и свежим хлебом, "
    "а над крышами кружат чайки. Вечером рыбаки чинят сети на причале, "
    "и закат окрашивает воду в оранжевый цвет."
)


def parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="soundpics",
        description="Показывает картинку на каждые 2-3 слова звучащей на устройстве речи.",
    )
    p.add_argument("--config", default="", help="путь к config.toml")
    p.add_argument("--backend", choices=["auto", "parecord", "ffmpeg", "pw-record"],
                   help="принудительно выбрать способ захвата звука")
    p.add_argument("--device", help="имя monitor-источника (см. --list-devices)")
    p.add_argument("--model", help="модель Whisper: tiny|base|small|medium")
    p.add_argument("--language", help="язык распознавания: ru|en|'' (авто)")
    p.add_argument("--chunk", type=float, help="длина куска аудио, сек")
    p.add_argument("--trigger", type=int, help="сколько слов копить до запроса")
    p.add_argument("--max-words", type=int, help="максимум слов в одном запросе")
    p.add_argument("--interval", type=float, help="пауза между поисками картинок, сек")
    p.add_argument("--list-devices", action="store_true",
                   help="показать monitor-источники и выйти")
    p.add_argument("--dry-run", action="store_true",
                   help="не слушать аудио, а обработать текст (--text или встроенный пример)")
    p.add_argument("--text", help="файл с текстом для --dry-run")
    p.add_argument("--no-fetch", action="store_true",
                   help="только печатать запросы, не искать картинки")
    p.add_argument("--test-image", metavar="QUERY",
                   help="найти одну картинку по запросу и выйти")
    p.add_argument("-v", "--verbose", action="store_true", help="отладочный лог")
    return p.parse_args(argv)


def _apply_overrides(cfg: dict, args: argparse.Namespace) -> None:
    if args.backend is not None:
        cfg["audio"]["backend"] = args.backend
    if args.device is not None:
        cfg["audio"]["device"] = args.device
    if args.model is not None:
        cfg["stt"]["model"] = args.model
    if args.language is not None:
        cfg["stt"]["language"] = args.language
    if args.chunk is not None:
        cfg["audio"]["chunk_seconds"] = args.chunk
    if args.trigger is not None:
        cfg["words"]["trigger"] = args.trigger
    if args.max_words is not None:
        cfg["words"]["max_per_query"] = args.max_words
    if args.interval is not None:
        cfg["words"]["min_interval"] = args.interval


def _print_devices() -> None:
    pulse = list_monitors()
    pw = list_monitors_pw()
    print("Monitor-источники (pactl):")
    for name in pulse or ["<не найдены>"]:
        print(f"  {name}")
    print("Monitor-узлы PipeWire (pw-dump):")
    for name in pw or ["<не найдены>"]:
        print(f"  {name}")
    if not pulse and not pw:
        print("\nСовет: установите pulseaudio-utils или pipewire-bin, затем "
              "включите что-нибудь со звуком и запустите снова.")


def _make_provider(cfg: dict) -> ImageProvider:
    img = cfg["images"]
    return ImageProvider(
        providers=img["providers"],
        cache_dir=img["cache_dir"],
        prefer=img["prefer"],
        timeout=float(img["timeout"]),
    )


def _dry_run(cfg: dict, args: argparse.Namespace) -> None:
    if args.text:
        text = Path(args.text).read_text(encoding="utf-8")
    else:
        text = DEMO_TEXT
    kw = KeywordExtractor(
        trigger=int(cfg["words"]["trigger"]),
        max_per_query=int(cfg["words"]["max_per_query"]),
    )
    provider = None if args.no_fetch else _make_provider(cfg)
    total = 0
    for piece in re.split(r"(?<=[.!?])\s+|\n+", text):
        piece = piece.strip()
        if not piece:
            continue
        for query in kw.feed(piece, allow_emit=True):
            total += 1
            print(f"[{total:02d}] {query}")
            if provider:
                try:
                    res = provider.get(query)
                    print(f"      → {res.provider}: {res.path}")
                except Exception as exc:
                    print(f"      → ошибка: {exc}")
    print(f"\nИтого запросов: {total}")


def _run_live(cfg: dict) -> None:
    from .stt import FasterWhisperSTT

    audio_cfg = cfg["audio"]
    _, cmd = resolve(audio_cfg["backend"], audio_cfg["device"], int(audio_cfg["rate"]))
    stt = FasterWhisperSTT(
        model=cfg["stt"]["model"],
        language=cfg["stt"]["language"],
        device=cfg["stt"]["device"],
        compute_type=cfg["stt"]["compute_type"],
    )
    capture = AudioCapture(cmd, int(audio_cfg["rate"]), float(audio_cfg["chunk_seconds"]))
    kw = KeywordExtractor(
        trigger=int(cfg["words"]["trigger"]),
        max_per_query=int(cfg["words"]["max_per_query"]),
    )
    provider = _make_provider(cfg)

    ui = ImageWindow(cfg["ui"])
    stop = threading.Event()
    ui.on_close = stop.set

    search_q: queue.Queue = queue.Queue(maxsize=4)
    ui_q: queue.Queue = queue.Queue(maxsize=3)
    lock = threading.Lock()
    last_search = [0.0]
    min_interval = float(cfg["words"]["min_interval"])

    def recognizer() -> None:
        while not stop.is_set():
            try:
                chunk = capture.q.get(timeout=0.5)
            except queue.Empty:
                continue
            if chunk is None:
                log.warning("Поток аудио завершился")
                put_dropold(ui_q, {
                    "type": "status",
                    "text": "Запись звука остановлена. Проверьте --list-devices и --device",
                })
                break
            try:
                text = stt.transcribe(chunk)
            except Exception as exc:
                log.warning("Ошибка распознавания: %s", exc)
                continue
            if not text:
                continue
            log.info("Речь: %s", text)
            with lock:
                allowed = (time.monotonic() - last_search[0]) >= min_interval
            for query in kw.feed(text, allow_emit=allowed):
                with lock:
                    last_search[0] = time.monotonic()
                put_dropold(search_q, query)
                put_dropold(ui_q, {"type": "status", "text": f"Ищу картинку: {query}"})

    def fetcher() -> None:
        while not stop.is_set():
            try:
                query = search_q.get(timeout=0.5)
            except queue.Empty:
                continue
            try:
                res = provider.get(query)
            except Exception as exc:
                log.warning("Поиск картинки «%s»: %s", query, exc)
                put_dropold(ui_q, {"type": "status", "text": f"Не нашлось: {query}"})
                continue
            put_dropold(ui_q, {
                "type": "image",
                "path": str(res.path),
                "query": query,
                "provider": res.provider,
            })

    capture.start()
    threads = [
        threading.Thread(target=recognizer, name="recognizer", daemon=True),
        threading.Thread(target=fetcher, name="fetcher", daemon=True),
    ]
    for t in threads:
        t.start()
    try:
        ui.run(ui_q)
    finally:
        stop.set()
        capture.stop()
        for t in threads:
            t.join(timeout=2.0)


def main(argv=None) -> int:
    args = parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    cfg = load_config(args.config)
    _apply_overrides(cfg, args)
    log.debug("Конфиг: %s", cfg.get("_config_path", "<значения по умолчанию>"))

    try:
        if args.list_devices:
            _print_devices()
        elif args.test_image is not None:
            res = _make_provider(cfg).get(args.test_image)
            print(res.path)
        elif args.dry_run or args.text is not None:
            _dry_run(cfg, args)
        else:
            _run_live(cfg)
    except KeyboardInterrupt:
        log.info("Выход по Ctrl+C")
    except RuntimeError as exc:
        log.error("%s", exc)
        return 1
    except Exception as exc:
        log.exception("Непредвиденная ошибка: %s", exc)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
