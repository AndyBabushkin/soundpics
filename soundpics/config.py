"""Конфигурация SoundPics: значения по умолчанию + config.toml."""
from __future__ import annotations

import copy
import tomllib
from pathlib import Path

DEFAULTS: dict = {
    "audio": {
        "backend": "auto",
        "device": "",
        "rate": 16000,
        "chunk_seconds": 3.0,
    },
    "stt": {
        "model": "small",
        "language": "ru",
        "device": "cpu",
        "compute_type": "int8",
    },
    "words": {
        "trigger": 2,
        "max_per_query": 3,
        "min_interval": 4.0,
    },
    "images": {
        "providers": ["openverse", "wikimedia"],
        "cache_dir": "~/.cache/soundpics",
        "prefer": "random",
        "timeout": 15,
    },
    "ui": {
        "always_on_top": True,
        "width": 900,
        "height": 650,
        "fullscreen": False,
    },
}


def _merge(base: dict, update: dict) -> dict:
    for key, value in update.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _merge(base[key], value)
        else:
            base[key] = value
    return base


def load_config(path: str = "") -> dict:
    """Загружает config.toml поверх значений по умолчанию.

    Порядок поиска: явный path → ./config.toml → ~/.config/soundpics/config.toml.
    Ключ "_config_path" содержит путь к использованному файлу (или отсутствует).
    """
    cfg = copy.deepcopy(DEFAULTS)
    if path:
        candidates = [Path(path).expanduser()]
    else:
        candidates = [
            Path("config.toml"),
            Path.home() / ".config" / "soundpics" / "config.toml",
        ]
    for candidate in candidates:
        if candidate.is_file():
            with candidate.open("rb") as fh:
                user = tomllib.load(fh)
            _merge(cfg, user)
            cfg["_config_path"] = str(candidate)
            break
    return cfg
