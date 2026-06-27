import os
import platform
from pathlib import Path
from dotenv import load_dotenv

def _ensure_env():
    from .paths import get_data_dir
    load_dotenv(get_data_dir() / ".env")

def _platform_os() -> str:
    return {"Windows": "windows", "Darwin": "mac", "Linux": "linux"}.get(
        platform.system(), "linux"
    )

def get_config() -> dict:
    _ensure_env()
    return {
        "gemini_api_key": os.getenv("GEMINI_API_KEY", ""),
        "openai_api_key": os.getenv("OPENAI_API_KEY", ""),
        "llm_provider": os.getenv("LLM_PROVIDER", "gemini"),
        "openai_base_url": os.getenv("OPENAI_BASE_URL", ""),
        "ollama_base_url": os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1"),
        "os_system": os.getenv("OS_SYSTEM", _platform_os()),
    }

def get_os() -> str:
    _ensure_env()
    return os.getenv("OS_SYSTEM", _platform_os()).lower()

def is_windows() -> bool: return get_os() == "windows"
def is_mac()     -> bool: return get_os() == "mac"
def is_linux()   -> bool: return get_os() == "linux"
