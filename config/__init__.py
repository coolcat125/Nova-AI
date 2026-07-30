import os
import platform
from pathlib import Path
from dotenv import load_dotenv

def _ensure_env():
    from .paths import get_data_dir
    data_dir = get_data_dir()
    env_path = data_dir / ".env"
    defaults_path = Path(__file__).parent.parent / "defaults.env"

    # Copy defaults.env to .env if missing
    if not env_path.exists() and defaults_path.exists():
        env_path.write_text(defaults_path.read_text(encoding="utf-8"), encoding="utf-8")

    # Load defaults as fallback, then .env overrides
    if defaults_path.exists():
        load_dotenv(defaults_path, override=False)
    load_dotenv(env_path, override=True)

    # Append any missing keys from defaults.env to .env
    if defaults_path.exists() and env_path.exists():
        existing = env_path.read_text(encoding="utf-8")
        defaults = defaults_path.read_text(encoding="utf-8")
        missing = []
        for line in defaults.splitlines():
            if line.strip() and not line.startswith("#") and "=" in line:
                key = line.split("=", 1)[0]
                if key not in existing:
                    missing.append(line)
        if missing:
            with open(env_path, "a", encoding="utf-8") as f:
                f.write("\n" + "\n".join(missing) + "\n")

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
