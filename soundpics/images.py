"""Поиск и загрузка картинок. Источники бесплатные и без ключей:
- Openverse (api.openverse.org) — творчество под свободными лицензиями;
- Wikimedia Commons — картинки со свободными лицензиями.
Результат кэшируется на диске по тексту запроса.
"""
from __future__ import annotations

import hashlib
import logging
import random
from dataclasses import dataclass
from pathlib import Path

import requests

log = logging.getLogger("soundpics.images")

UA = "soundpics/1.0 (personal project)"

_M = 20 * 1024 * 1024  # максимум скачиваемого файла


@dataclass
class FoundImage:
    path: Path
    query: str
    provider: str
    url: str


def _ext_from_magic(data: bytes) -> str | None:
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return ".webp"
    if data.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return ".gif"
    if data.startswith(b"BM"):
        return ".bmp"
    return None


def _openverse_urls(query: str, timeout: float) -> list[str]:
    r = requests.get(
        "https://api.openverse.org/v1/images/",
        params={"q": query, "page_size": 5},
        headers={"User-Agent": UA},
        timeout=timeout,
    )
    r.raise_for_status()
    results = r.json().get("results") or []
    return [it["url"] for it in results if it.get("url")]


def _wikimedia_urls(query: str, timeout: float) -> list[str]:
    params = {
        "action": "query",
        "format": "json",
        "generator": "search",
        "gsrsearch": f"filetype:bitmap {query}",
        "gsrnamespace": "6",
        "gsrlimit": "5",
        "prop": "imageinfo",
        "iiprop": "url",
        "iiurlwidth": "1280",
    }
    r = requests.get(
        "https://commons.wikimedia.org/w/api.php",
        params=params,
        headers={"User-Agent": UA},
        timeout=timeout,
    )
    r.raise_for_status()
    pages = (r.json().get("query") or {}).get("pages") or {}
    urls = []
    for page in pages.values():
        info = (page.get("imageinfo") or [{}])[0]
        url = info.get("thumburl") or info.get("url")
        if url:
            urls.append(url)
    return urls


_OPENERS = {"openverse": _openverse_urls, "wikimedia": _wikimedia_urls}


class ImageProvider:
    def __init__(self, providers=("openverse", "wikimedia"),
                 cache_dir: str = "~/.cache/soundpics",
                 prefer: str = "random", timeout: float = 15.0):
        self.providers = [p for p in providers if p in _OPENERS]
        if not self.providers:
            raise ValueError(f"Неизвестные провайдеры: {providers!r}")
        self.cache_dir = Path(cache_dir).expanduser()
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.prefer = prefer
        self.timeout = float(timeout)
        self.session = requests.Session()

    def search_urls(self, query: str) -> tuple[str, list[str]]:
        """Возвращает (провайдер, список URL); при неудаче перебирает провайдеров."""
        for name in self.providers:
            try:
                urls = _OPENERS[name](query, self.timeout)
            except Exception as exc:
                log.warning("%s: %s", name, exc)
                continue
            urls = [u for u in urls if u.startswith(("http://", "https://"))]
            if urls:
                return name, urls
        raise RuntimeError("ни один источник не дал ссылок")

    def _variants(self, query: str) -> list[str]:
        """Запрос и откаты: полный → слова по одному (с конца к началу).

        Нужно потому, что поиск по фразе из 2-3 слов часто слишком строг
        (особенно Wikimedia: «filetype:bitmap слово1 слово2 слово3» = AND по всем).
        """
        words = query.split()
        variants = [query, *reversed(words)]
        seen: set[str] = set()
        out = []
        for v in variants:
            if v not in seen:
                seen.add(v)
                out.append(v)
        return out

    def get(self, query: str) -> FoundImage:
        """Находит и скачивает картинку по запросу; использует дисковый кэш."""
        key = hashlib.sha1(query.lower().encode("utf-8")).hexdigest()[:16]
        for ext in (".jpg", ".png", ".webp", ".gif", ".bmp"):
            cached = self.cache_dir / f"{key}{ext}"
            if cached.exists() and cached.stat().st_size > 2048:
                return FoundImage(cached, query, "cache", "")

        last_err: Exception | None = None
        for variant in self._variants(query):
            try:
                name, urls = self.search_urls(variant)
                url = urls[0] if self.prefer == "first" else random.choice(urls)
                data = self._download(url)
                ext = _ext_from_magic(data)
                if ext is None:
                    raise RuntimeError("ответ не похож на картинку")
                if len(data) < 2048:
                    raise RuntimeError("слишком маленький файл")
                path = self.cache_dir / f"{key}{ext}"
                path.write_bytes(data)
                log.info("%s: %s (вариант «%s») → %s", name, query, variant, path)
                return FoundImage(path, query, name, url)
            except Exception as exc:
                last_err = exc
                log.debug("Вариант «%s» не удался: %s", variant, exc)
        raise RuntimeError(f"ни один источник не дал ссылок ({last_err})")

    def _download(self, url: str) -> bytes:
        with self.session.get(
            url,
            headers={"User-Agent": UA, "Accept": "image/*,*/*;q=0.8"},
            timeout=self.timeout,
            stream=True,
        ) as r:
            r.raise_for_status()
            chunks = []
            total = 0
            for part in r.iter_content(64 * 1024):
                total += len(part)
                if total > _M:
                    raise RuntimeError("файл больше 20 МБ")
                chunks.append(part)
            return b"".join(chunks)
