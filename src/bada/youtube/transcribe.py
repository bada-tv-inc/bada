"""Speech-to-text with faster-whisper (runs locally, no API key)."""
from __future__ import annotations

from pathlib import Path

from bada.youtube.timeline import Segment


def transcribe(path: Path, model_size: str = "small", language: str | None = "ko") -> list[Segment]:
    try:
        from faster_whisper import WhisperModel
    except ImportError as e:
        raise RuntimeError("faster-whisper is not installed. Run: pip install 'bada[youtube]'") from e

    model = WhisperModel(model_size, device="auto", compute_type="auto")
    raw, _info = model.transcribe(str(path), language=language, vad_filter=True)
    return [Segment(i, s.start, s.end, s.text.strip()) for i, s in enumerate(raw) if s.text.strip()]
