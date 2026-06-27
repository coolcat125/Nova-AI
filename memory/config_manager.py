"""Formal config manager. All config lives in a memory/api_keys.json file."""

from __future__ import annotations
import json
import os
from pathlib import Path
from threading import Lock


from config.paths import get_data_dir

CONFIG_DIR = get_data_dir() / "memory"
CONFIG_PATH = CONFIG_DIR / "api_keys.json"
_lock = Lock()


def _default_config() -> dict:
    return {
        "llm_provider": "gemini",
        "os_system": "windows",
        "gemini_api_key": "",
        "openai_api_key": "",
        "openai_base_url": "",
        "ollama_base_url": "http://localhost:11434/v1",
    }


def load_config() -> dict:
    if not CONFIG_PATH.exists():
        config = _default_config()
        save_config(config)
        return config
    with _lock:
        try:
            data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                return _default_config()
            base = _default_config()
            for key in base:
                if key not in data:
                    data[key] = base[key]
            return data
        except Exception:
            return _default_config()


def save_config(config: dict) -> None:
    if not isinstance(config, dict):
        return
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with _lock:
        CONFIG_PATH.write_text(
            json.dumps(config, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )


def is_configured() -> bool:
    config = load_config()
    prov = config.get("llm_provider", "gemini")
    if prov == "gemini":
        return bool(config.get("gemini_api_key"))
    elif prov == "openai":
        return bool(config.get("openai_api_key"))
    elif prov == "ollama":
        return True
    return False


def apply_to_environ(config: dict = None) -> None:
    if config is None:
        config = load_config()
    os.environ["LLM_PROVIDER"] = config.get("llm_provider", "gemini")
    os.environ["OS_SYSTEM"] = config.get("os_system", "windows")
    os.environ["GEMINI_API_KEY"] = config.get("gemini_api_key", "")
    os.environ["OPENAI_API_KEY"] = config.get("openai_api_key", "")
    url = config.get("openai_base_url", "")
    if url:
        os.environ["OPENAI_BASE_URL"] = url
    url = config.get("ollama_base_url", "http://localhost:11434/v1")
    if url:
        os.environ["OLLAMA_BASE_URL"] = url


def save_from_env() -> dict:
    config = {
        "llm_provider": os.environ.get("LLM_PROVIDER", "gemini"),
        "os_system": os.environ.get("OS_SYSTEM", "windows"),
        "gemini_api_key": os.environ.get("GEMINI_API_KEY", ""),
        "openai_api_key": os.environ.get("OPENAI_API_KEY", ""),
        "openai_base_url": os.environ.get("OPENAI_BASE_URL", ""),
        "ollama_base_url": os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434/v1"),
    }
    save_config(config)
    return config


def set_provider(provider: str) -> dict:
    valid = {"gemini", "openai", "ollama"}
    if provider not in valid:
        raise ValueError(f"Invalid provider: {provider}. Use: {valid}")
    config = load_config()
    config["llm_provider"] = provider
    save_config(config)
    apply_to_environ(config)
    return config
