# config/__init__.py
import os
from pathlib import Path
from dotenv import load_dotenv

def _ensure_env():
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")

def get_config() -> dict:
    _ensure_env()
    return {
        "gemini_api_key": os.getenv("GEMINI_API_KEY", ""),
        "os_system": os.getenv("OS_SYSTEM", "windows"),
    }

def get_os() -> str:
    _ensure_env()
    return os.getenv("OS_SYSTEM", "windows").lower()

def is_windows() -> bool: return get_os() == "windows"
def is_mac()     -> bool: return get_os() == "mac"
def is_linux()   -> bool: return get_os() == "linux"
