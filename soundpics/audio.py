"""Захват системного звука (loopback) через monitor-источник PulseAudio/PipeWire.

Схема: находим monitor основного вывода (pactl/pw-dump), запускаем рекордер,
который пишет сырой PCM (s16le, моно, 16 кГц) в stdout, и читаем его кусками.
"""
from __future__ import annotations

import json
import logging
import queue
import shutil
import subprocess
import threading

import numpy as np

log = logging.getLogger("soundpics.audio")

BACKENDS = ("parecord", "ffmpeg", "pw-record")


def _run(cmd: list[str], timeout: float = 10.0) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def _default_sink() -> str | None:
    try:
        out = _run(["pactl", "get-default-sink"])
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    return out.stdout.strip() if out.returncode == 0 else None


def list_monitors() -> list[str]:
    """Monitor-источники через pactl (PulseAudio/PipeWire)."""
    try:
        out = _run(["pactl", "list", "short", "sources"])
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        log.debug("pactl недоступен: %s", exc)
        return []
    if out.returncode != 0:
        return []
    names = []
    for line in out.stdout.splitlines():
        parts = line.split("\t")
        if len(parts) >= 2 and parts[1].strip().endswith(".monitor"):
            names.append(parts[1].strip())
    default = _default_sink()
    if default:
        names.sort(key=lambda n: n != f"{default}.monitor")  # monitor основного вывода — первым
    return names


def list_monitors_pw() -> list[str]:
    """Monitor-узлы PipeWire через pw-dump (запасной вариант без pactl)."""
    if not shutil.which("pw-dump"):
        return []
    try:
        out = subprocess.run(["pw-dump"], capture_output=True, text=True, timeout=10)
    except subprocess.TimeoutExpired:
        return []
    if out.returncode != 0:
        return []
    try:
        nodes = json.loads(out.stdout)
    except json.JSONDecodeError:
        return []
    names = []
    for node in nodes:
        props = (node.get("info") or {}).get("props") or {}
        name = props.get("node.name") or ""
        if name.endswith(".monitor"):
            names.append(name)
    return names


def build_command(backend: str, device: str, rate: int) -> list[str] | None:
    """Команда, пишущая сырой PCM в stdout, или None если бинаря нет."""
    if backend == "parecord" and shutil.which("parecord"):
        return [
            "parecord", "--raw",
            f"--device={device}", "--format=s16le",
            f"--rate={rate}", "--channels=1",
        ]
    if backend == "ffmpeg" and shutil.which("ffmpeg"):
        return [
            "ffmpeg", "-hide_banner", "-loglevel", "error",
            "-f", "pulse", "-i", device,
            "-ar", str(rate), "-ac", "1",
            "-f", "s16le", "-acodec", "pcm_s16le", "pipe:1",
        ]
    if backend == "pw-record" and shutil.which("pw-record") and device:
        return [
            "pw-record", "--format=s16",
            f"--rate={rate}", "--channels=1",
            f"--target={device}", "-",
        ]
    return None


def resolve(backend: str, device: str, rate: int) -> tuple[str, list[str]]:
    """Выбирает доступный бэкенд захвата; возвращает (имя, команда)."""
    if device:
        names = {"parecord": device, "ffmpeg": device, "pw-record": device}
    else:
        pulse = list_monitors()
        pw = list_monitors_pw()
        names = {
            "parecord": pulse[0] if pulse else "monitor",
            "ffmpeg": pulse[0] if pulse else "monitor",
            "pw-record": pulse[0] if pulse else (pw[0] if pw else ""),
        }
    order = list(BACKENDS) if backend == "auto" else [backend]
    for name in order:
        cmd = build_command(name, names[name], rate)
        if cmd:
            log.info("Захват звука через %s (%s)", name, names[name])
            return name, cmd
    raise RuntimeError(
        "Не найдено средство захвата звука. Установите одно из: "
        "pulseaudio-utils (parecord), ffmpeg, pipewire-bin (pw-record).\n"
        "Устройства можно посмотреть так: run.py --list-devices"
    )


def put_dropold(q: queue.Queue, item) -> None:
    """Положить в очередь, выбросив самый старый элемент при переполнении."""
    try:
        q.put_nowait(item)
    except queue.Full:
        try:
            q.get_nowait()
        except queue.Empty:
            pass
        try:
            q.put_nowait(item)
        except queue.Full:
            pass


class AudioCapture:
    """Читает сырой PCM (s16le, моно) из процесса-рекордера и отдаёт куски по очереди."""

    def __init__(self, cmd: list[str], rate: int, chunk_seconds: float,
                 max_queue: int = 8):
        self.cmd = cmd
        self.rate = rate
        self.chunk_bytes = int(rate * chunk_seconds) * 2
        self.q: queue.Queue = queue.Queue(maxsize=max_queue)
        self._stop = threading.Event()
        self._proc: subprocess.Popen | None = None

    def start(self) -> None:
        self._proc = subprocess.Popen(
            self.cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=0
        )
        threading.Thread(target=self._drain_stderr, daemon=True).start()
        threading.Thread(target=self._reader, daemon=True).start()
        log.info("Команда записи: %s", " ".join(self.cmd))

    def _drain_stderr(self) -> None:
        assert self._proc is not None and self._proc.stderr is not None
        for raw in iter(self._proc.stderr.readline, b""):
            line = raw.decode(errors="replace").rstrip()
            if line:
                log.debug("recorder[%s]: %s", self.cmd[0], line)

    def _reader(self) -> None:
        assert self._proc is not None and self._proc.stdout is not None
        while not self._stop.is_set():
            data = self._read_exact(self.chunk_bytes)
            if data is None:
                break
            chunk = np.frombuffer(data, dtype="<i2").astype(np.float32) / 32768.0
            put_dropold(self.q, chunk)
        put_dropold(self.q, None)  # sentinel: поток закончился

    def _read_exact(self, n: int) -> bytes | None:
        assert self._proc is not None and self._proc.stdout is not None
        buf = bytearray()
        while len(buf) < n:
            if self._stop.is_set():
                return None
            part = self._proc.stdout.read(n - len(buf))
            if not part:
                log.warning("recorder[%s] завершился", self.cmd[0])
                return None
            buf.extend(part)
        return bytes(buf)

    def stop(self) -> None:
        self._stop.set()
        if self._proc and self._proc.poll() is None:
            self._proc.terminate()
