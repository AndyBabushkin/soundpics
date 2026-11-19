"""Окно с картинкой (Tkinter). Потокобезопасно: обновления приходят через очередь
и применяются в главном потоке через root.after()."""
from __future__ import annotations

import logging
import queue

import tkinter as tk

from PIL import Image, ImageTk

log = logging.getLogger("soundpics.gui")


class ImageWindow:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.on_close = None
        self._pil: Image.Image | None = None
        self._photo: ImageTk.PhotoImage | None = None
        self._render_job: str | None = None

        try:
            self.root = tk.Tk()
        except tk.TclError as exc:
            raise RuntimeError(
                "Не удалось открыть окно: похоже, нет графической сессии "
                f"(DISPLAY не задан). Запустите приложение в сессии с рабочим столом. ({exc})"
            ) from exc
        self.root.title("SoundPics")
        self.root.geometry(f"{int(cfg.get('width', 900))}x{int(cfg.get('height', 650))}+30+30")
        self.root.minsize(320, 240)
        self.root.configure(bg="black")

        self.canvas = tk.Canvas(self.root, bg="black", highlightthickness=0)
        self.canvas.pack(fill=tk.BOTH, expand=True)

        bar = tk.Frame(self.root, bg="#101010")
        bar.pack(side=tk.BOTTOM, fill=tk.X)
        self.status = tk.Label(
            bar, text="Слушаю системный звук…", fg="#d0d0d0", bg="#101010",
            anchor="w", padx=10, pady=6,
        )
        self.status.pack(side=tk.LEFT, fill=tk.X, expand=True)
        hint = tk.Label(
            bar, text="Q — выход   F — во весь экран   T — поверх всех",
            fg="#6a6a6a", bg="#101010", padx=10, pady=6,
        )
        hint.pack(side=tk.RIGHT)

        self.root.attributes("-topmost", bool(cfg.get("always_on_top", True)))
        if cfg.get("fullscreen"):
            self.root.attributes("-fullscreen", True)

        for key in ("q", "Q", "<Escape>"):
            self.root.bind(key, lambda e: self._quit())
        for key in ("f", "F"):
            self.root.bind(key, lambda e: self._toggle_fullscreen())
        for key in ("t", "T"):
            self.root.bind(key, lambda e: self._toggle_topmost())
        self.root.bind("<Configure>", self._on_configure)
        self.root.protocol("WM_DELETE_WINDOW", self._quit)

        self._show_placeholder()
        self._render()

    # --- публичное API -------------------------------------------------

    def set_status(self, text: str) -> None:
        self.status.configure(text=text)

    def set_image(self, path: str) -> None:
        try:
            img = Image.open(path)
            img.load()
        except Exception as exc:
            log.warning("Не удалось открыть %s: %s", path, exc)
            return
        self._pil = img.convert("RGB")
        self._render()

    def poll(self, q: queue.Queue) -> None:
        """Забирает самое свежее сообщение из очереди (старые отбрасывает)."""
        item = None
        while True:
            try:
                item = q.get_nowait()
            except queue.Empty:
                break
        if item:
            kind = item.get("type")
            if kind == "status":
                self.set_status(item.get("text", ""))
            elif kind == "image":
                self.set_status(f"{item.get('query', '')} · {item.get('provider', '')}")
                self.set_image(item["path"])
        self.root.after(120, lambda: self.poll(q))

    def run(self, q: queue.Queue) -> None:
        self.poll(q)
        self.root.mainloop()

    # --- внутреннее ----------------------------------------------------

    def _show_placeholder(self) -> None:
        self.canvas.delete("all")
        w = self.canvas.winfo_width()
        h = self.canvas.winfo_height()
        if w <= 1:
            w = int(self.cfg.get("width", 900))
        if h <= 1:
            h = int(self.cfg.get("height", 650))
        self.canvas.create_text(
            w // 2, h // 2 - 16, text="Здесь появится картинка",
            fill="#8a8a8a", font=("DejaVu Sans", 18),
        )
        self.canvas.create_text(
            w // 2, h // 2 + 20, text="Включите что-нибудь со звуком 🙂",
            fill="#5a5a5a", font=("DejaVu Sans", 12),
        )

    def _on_configure(self, event) -> None:
        if event.widget is not self.root:
            return
        if self._pil is None:
            self._show_placeholder()
            return
        if self._render_job:
            self.root.after_cancel(self._render_job)
        self._render_job = self.root.after(80, self._render)

    def _render(self) -> None:
        if self._pil is None:
            return
        w = self.canvas.winfo_width()
        h = self.canvas.winfo_height()
        if w <= 1 or h <= 1:
            return
        img = self._pil.copy()
        img.thumbnail((w, h), Image.LANCZOS)
        self._photo = ImageTk.PhotoImage(img)
        self.canvas.delete("all")
        self.canvas.create_image(
            (w - img.width) // 2, (h - img.height) // 2,
            anchor="nw", image=self._photo,
        )

    def _toggle_fullscreen(self) -> None:
        state = bool(self.root.attributes("-fullscreen"))
        self.root.attributes("-fullscreen", not state)

    def _toggle_topmost(self) -> None:
        state = bool(self.root.attributes("-topmost"))
        self.root.attributes("-topmost", not state)

    def _quit(self) -> None:
        if self.on_close:
            self.on_close()
        self.root.destroy()
