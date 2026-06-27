"""Enhanced Ollama provider. Auto-launch serve, warmup, auto-retry."""

import os
import subprocess
import sys
import threading
import time
from typing import Optional

import requests
from .base import BaseLLM

_SERVE_PROC: Optional[subprocess.Popen] = None
_SERVE_LOCK = threading.Lock()


def _find_ollama() -> Optional[str]:
    """Find ollama.exe on PATH or common install locations."""
    try:
        result = subprocess.run(["where", "ollama"], capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            return result.stdout.strip().split("\n")[0].strip()
    except Exception:
        pass
    candidates = [
        os.path.expandvars(r"%LOCALAPPDATA%\Programs\Ollama\ollama.exe"),
        os.path.expandvars(r"%PROGRAMFILES%\Ollama\ollama.exe"),
        r"C:\Program Files\Ollama\ollama.exe",
    ]
    for c in candidates:
        if os.path.exists(c):
            return c
    return None


def _is_ollama_serving() -> bool:
    try:
        r = requests.get("http://localhost:11434/api/tags", timeout=2)
        return r.status_code == 200
    except Exception:
        return False


def _ensure_ollama_serve(timeout: float = 15.0) -> bool:
    global _SERVE_PROC
    if _is_ollama_serving():
        return True
    with _SERVE_LOCK:
        if _is_ollama_serving():
            return True
        exe = _find_ollama()
        if not exe:
            print("[Ollama] ollama not found on PATH")
            return False
        try:
            startupinfo = None
            if sys.platform == "win32":
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            _SERVE_PROC = subprocess.Popen(
                [exe, "serve"],
                startupinfo=startupinfo,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            deadline = time.time() + timeout
            while time.time() < deadline:
                if _is_ollama_serving():
                    print("[Ollama] serve started")
                    return True
                time.sleep(0.5)
            print("[Ollama] serve start timed out")
            return False
        except Exception as e:
            print(f"[Ollama] serve launch failed: {e}")
            return False


def _warmup_model(model: str, timeout: float = 60.0) -> bool:
    if _is_model_loaded(model):
        return True
    print(f"[Ollama] Warming up {model}...")
    try:
        r = requests.post(
            "http://localhost:11434/api/generate",
            json={"model": model, "prompt": "hello", "stream": False, "keep_alive": "5m"},
            timeout=timeout,
        )
        ok = r.status_code == 200
        if ok:
            print(f"[Ollama] {model} warmed up")
        else:
            print(f"[Ollama] warmup failed: {r.status_code}")
        return ok
    except Exception as e:
        print(f"[Ollama] warmup error: {e}")
        return False


def _is_model_loaded(model: str) -> bool:
    try:
        r = requests.get("http://localhost:11434/api/show", json={"model": model}, timeout=5)
        return r.status_code == 200
    except Exception:
        return False


def _stream_generate(model: str, messages: list) -> dict:
    """Send request to Ollama generate API with streaming, return aggregated result."""
    prompt = _messages_to_prompt(messages)
    try:
        r = requests.post(
            "http://localhost:11434/api/generate",
            json={"model": model, "prompt": prompt, "stream": False, "options": {"num_predict": 2048}},
            timeout=120,
        )
        if r.status_code != 200:
            return {"content": f"Error: HTTP {r.status_code}", "tool_calls": [], "finish_reason": "error"}
        data = r.json()
        text = data.get("response", "")
        return {"content": text, "tool_calls": [], "finish_reason": "stop"}
    except Exception as e:
        return {"content": f"Error: {e}", "tool_calls": [], "finish_reason": "error"}


def _messages_to_prompt(messages: list) -> str:
    parts = []
    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        if role == "system":
            parts.append(f"System: {content}")
        elif role == "user":
            parts.append(f"User: {content}")
        elif role == "assistant":
            parts.append(f"Assistant: {content}")
    return "\n".join(parts)


class OllamaProvider(BaseLLM):
    """Ollama provider with auto-launch, warmup, and sentence-split streaming."""

    def __init__(self):
        base_url = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434/v1")
        self._base_url = base_url.rstrip("/")
        self._sentence_mode = True
        _ensure_ollama_serve()

    def generate(self, model: str, system_instruction: Optional[str] = None,
                 messages: Optional[list] = None, contents: Optional[str] = None,
                 tools: Optional[list] = None, **kwargs) -> dict:
        if not _is_ollama_serving():
            ok = _ensure_ollama_serve()
            if not ok:
                return {"content": "Error: Ollama server not available", "tool_calls": [], "finish_reason": "error"}

        warmup = kwargs.pop("warmup", True)
        if warmup:
            _warmup_model(model)

        msgs = []
        if system_instruction:
            msgs.append({"role": "system", "content": system_instruction})
        if messages:
            msgs.extend(messages)
        elif contents:
            msgs.append({"role": "user", "content": contents})
        else:
            msgs.append({"role": "user", "content": ""})

        return _stream_generate(model, msgs)
