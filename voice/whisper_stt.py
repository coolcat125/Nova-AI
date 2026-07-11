"""Whisper STT via faster-whisper. Runs locally, no API key."""

import io
import numpy as np
from pathlib import Path

_model = None
MODEL_SIZE = "small.en"
SAMPLE_RATE = 16000


def _get_model():
    global _model
    if _model is None:
        from faster_whisper import WhisperModel
        _model = WhisperModel(MODEL_SIZE, device="cpu", compute_type="int8")
    return _model


def transcribe(audio_bytes: bytes, sample_rate: int = SAMPLE_RATE) -> str:
    """Transcribe raw PCM int16 audio bytes to text.

    Args:
        audio_bytes: Raw PCM audio (int16, mono).
        sample_rate: Sample rate of the audio (default 16000).

    Returns:
        Transcribed text, or empty string if nothing detected.
    """
    model = _get_model()

    audio_np = np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32) / 32768.0

    if len(audio_np) < sample_rate * 0.3:
        return ""

    segments, info = model.transcribe(
        audio_np,
        beam_size=5,
        language="en",
        vad_filter=True,
        vad_parameters=dict(min_silence_duration_ms=500),
    )

    text_parts = []
    for segment in segments:
        text_parts.append(segment.text.strip())

    return " ".join(text_parts).strip()
