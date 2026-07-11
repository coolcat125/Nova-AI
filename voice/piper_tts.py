"""Piper TTS. Runs locally, no API key."""

import io
import wave
import struct
from pathlib import Path

_voices = {}
VOICE_MODEL = "en_US-lessac-medium"
VOICE_CONFIG = "en_US-lessac-medium.onnx.json"


def _get_voice_dir() -> Path:
    """Get or create the voices directory."""
    voice_dir = Path(__file__).parent.parent / "voices"
    voice_dir.mkdir(exist_ok=True)
    return voice_dir


def _ensure_voice():
    """Download voice model if not present."""
    voice_dir = _get_voice_dir()
    model_path = voice_dir / f"{VOICE_MODEL}.onnx"
    if model_path.exists():
        return voice_dir

    print(f"[Piper] Downloading voice: {VOICE_MODEL}...")
    import urllib.request
    import json

    base_url = "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium"

    for fname in [f"{VOICE_MODEL}.onnx", VOICE_CONFIG]:
        url = f"{base_url}/{fname}"
        dest = voice_dir / fname
        if not dest.exists():
            print(f"[Piper] Downloading {fname}...")
            urllib.request.urlretrieve(url, str(dest))

    print(f"[Piper] Voice ready: {VOICE_MODEL}")
    return voice_dir


def synthesize(text: str, sample_rate: int = 22050) -> bytes:
    """Convert text to raw PCM int16 audio bytes.

    Args:
        text: Text to speak.
        sample_rate: Output sample rate (default 22050).

    Returns:
        Raw PCM int16 audio bytes.
    """
    from piper import PiperVoice

    voice_dir = _ensure_voice()
    model_path = voice_dir / f"{VOICE_MODEL}.onnx"

    if VOICE_MODEL not in _voices:
        _voices[VOICE_MODEL] = PiperVoice.load(str(model_path))

    voice = _voices[VOICE_MODEL]

    audio_chunks = []
    for chunk in voice.synthesize(text):
        audio_chunks.append(chunk)

    if not audio_chunks:
        return b""

    audio_data = b"".join(c.audio_int16_bytes for c in audio_chunks)

    return audio_data


def synthesize_to_wav(text: str) -> bytes:
    """Convert text to WAV audio bytes.

    Args:
        text: Text to speak.

    Returns:
        WAV file bytes.
    """
    pcm = synthesize(text)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(22050)
        wf.writeframes(pcm)
    return buf.getvalue()
