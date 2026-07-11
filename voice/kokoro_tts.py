"""Kokoro TTS via kokoro-onnx. Offline neural TTS, ~300MB model. Apache 2.0."""

import soundfile as sf
import numpy as np
from pathlib import Path

_model = None
_voices = None
SAMPLE_RATE = 24000
VOICE = "af_heart"


def _ensure_model():
    """Download model files if not present."""
    model_dir = Path(__file__).parent.parent / "models" / "kokoro"
    model_dir.mkdir(parents=True, exist_ok=True)

    onnx_path = model_dir / "kokoro-v1.0.onnx"
    voices_path = model_dir / "voices-v1.0.bin"

    if onnx_path.exists() and voices_path.exists():
        return model_dir

    import urllib.request
    base = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0"

    for fname in ["kokoro-v1.0.onnx", "voices-v1.0.bin"]:
        dest = model_dir / fname
        if not dest.exists():
            print(f"[Kokoro] Downloading {fname}...")
            urllib.request.urlretrieve(f"{base}/{fname}", str(dest))

    print("[Kokoro] Model ready.")
    return model_dir


def _get_model():
    global _model, _voices
    if _model is None:
        from kokoro_onnx import Kokoro
        model_dir = _ensure_model()
        _model = Kokoro(
            str(model_dir / "kokoro-v1.0.onnx"),
            str(model_dir / "voices-v1.0.bin"),
        )
    return _model


def preload():
    """Preload the Kokoro model to avoid first-synthesis delay."""
    _get_model()
    print("[Kokoro] Model preloaded.")


def synthesize(text: str) -> bytes:
    """Convert text to raw PCM int16 audio bytes.

    Args:
        text: Text to speak.

    Returns:
        Raw PCM int16 audio bytes, 24kHz mono.
    """
    model = _get_model()

    audio, sr = model.create(text, voice=VOICE, speed=1.0)

    audio_int16 = (audio * 32767).astype(np.int16)
    return audio_int16.tobytes()


def synthesize_to_wav(text: str) -> bytes:
    """Convert text to WAV audio bytes."""
    import io
    pcm = synthesize(text)
    buf = io.BytesIO()
    sf.write(buf, np.frombuffer(pcm, dtype=np.int16), SAMPLE_RATE, format="WAV")
    return buf.getvalue()
