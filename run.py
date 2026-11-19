#!/usr/bin/env python3
"""Запуск SoundPics."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from soundpics.main import main

if __name__ == "__main__":
    raise SystemExit(main())
