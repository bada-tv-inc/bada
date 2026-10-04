"""Speech-to-text with faster-whisper (runs locally, no API key)."""
from __future__ import annotations

from pathlib import Path

from bada.youtube.timeline import Segment

Word = tuple[float, float, str]  # start, end, text (with its leading space, as whisper emits it)


def _model(model_size: str):
    try:
        from faster_whisper import WhisperModel
    except ImportError as e:
        raise RuntimeError("faster-whisper is not installed. Run: pip install 'bada[youtube]'") from e
    return WhisperModel(model_size, device="auto", compute_type="auto")


def transcribe(path: Path, model_size: str = "small", language: str | None = "ko") -> list[Segment]:
    raw, _info = _model(model_size).transcribe(str(path), language=language, vad_filter=True)
    return [Segment(i, s.start, s.end, s.text.strip()) for i, s in enumerate(raw) if s.text.strip()]


def transcribe_words(path: Path, model_size: str = "small", language: str | None = "ko") -> list[Word]:
    raw, _info = _model(model_size).transcribe(str(path), language=language, word_timestamps=True)
    return [(w.start, w.end, w.word) for s in raw for w in (s.words or []) if w.word.strip()]
