"""Vosk STT. Instant load, ~50MB model. Runs locally, no API key."""

import json
import queue
from pathlib import Path

import numpy as np
from vosk import Model, KaldiRecognizer

_model = None
MODEL_NAME = "vosk-model-small-en-us-0.15"
SAMPLE_RATE = 16000


def _get_model() -> Model:
    global _model
    if _model is None:
        model_dir = Path(__file__).parent.parent / "models"
        model_dir.mkdir(exist_ok=True)
        model_path = model_dir / MODEL_NAME

        if not model_path.exists():
            print(f"[Vosk] Downloading model: {MODEL_NAME}...")
            import urllib.request
            import zipfile
            import io

            url = f"https://alphacephei.com/vosk/models/{MODEL_NAME}.zip"
            data = urllib.request.urlopen(url).read()
            with zipfile.ZipFile(io.BytesIO(data)) as zf:
                zf.extractall(str(model_dir))
            print(f"[Vosk] Model ready.")

        _model = Model(str(model_path))
    return _model


def preload():
    """Preload the Vosk model to avoid first-transcription delay."""
    _get_model()
    print("[Vosk] Model preloaded.")


def transcribe(audio_bytes: bytes, sample_rate: int = SAMPLE_RATE) -> str:
    """Transcribe raw PCM int16 audio bytes to text.

    Args:
        audio_bytes: Raw PCM audio (int16, mono).
        sample_rate: Sample rate of the audio (default 16000).

    Returns:
        Transcribed text, or empty string if nothing detected.
    """
    model = _get_model()
    rec = KaldiRecognizer(model, sample_rate)
    rec.SetWords(True)

    audio_np = np.frombuffer(audio_bytes, dtype=np.int16)
    if len(audio_np) < sample_rate * 0.3:
        return ""

    rec.AcceptWaveform(audio_np.tobytes())
    result = json.loads(rec.FinalResult())
    return result.get("text", "").strip()
