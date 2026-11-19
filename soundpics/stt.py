"""Распознавание речи: локальная модель faster-whisper (офлайн, приватно)."""
from __future__ import annotations

import logging

import numpy as np

log = logging.getLogger("soundpics.stt")


class FasterWhisperSTT:
    def __init__(self, model: str = "small", language: str = "ru",
                 device: str = "cpu", compute_type: str = "int8"):
        from faster_whisper import WhisperModel

        log.info("Загружаю модель Whisper '%s' (%s, %s)…", model, device, compute_type)
        self._model = WhisperModel(model, device=device, compute_type=compute_type)
        self.language = language or None

    def transcribe(self, pcm: np.ndarray) -> str:
        """pcm — float32 numpy, моно, 16 кГц. Возвращает распознанный текст."""
        segments, info = self._model.transcribe(
            pcm,
            language=self.language,
            beam_size=1,
            condition_on_previous_text=False,
        )
        text = " ".join(seg.text for seg in segments).strip()
        if text:
            log.debug("lang=%s logprob=%.2f: %s",
                      getattr(info, "language", "?"), getattr(info, "avg_logprob", 0.0), text)
        return text
