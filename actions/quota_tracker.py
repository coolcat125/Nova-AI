from __future__ import annotations
import json
import os
from datetime import date
from pathlib import Path


def _base_dir() -> Path:
    import sys
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


QUOTA_FILE = _base_dir() / "memory" / "quota.json"

_PROVIDER_LIMITS = {
    "gemini": 1500,
    "openai": 200,
    "ollama": 99999,
    "cerebras": 500,
}


def _detect_limit() -> int:
    prov = os.environ.get("LLM_PROVIDER", "gemini").strip().lower()
    return _PROVIDER_LIMITS.get(prov, 1500)


def get_model_name() -> str:
    from providers import get_current_model
    return get_current_model()


def _load() -> dict:
    if not QUOTA_FILE.exists():
        return {"date": str(date.today()), "count": 0}
    try:
        data = json.loads(QUOTA_FILE.read_text("utf-8"))
        if data.get("date") != str(date.today()):
            return {"date": str(date.today()), "count": 0}
        return data
    except Exception:
        return {"date": str(date.today()), "count": 0}


def increment():
    data = _load()
    data["count"] = data.get("count", 0) + 1
    QUOTA_FILE.parent.mkdir(parents=True, exist_ok=True)
    QUOTA_FILE.write_text(json.dumps(data), encoding="utf-8")


def get_usage() -> tuple:
    data = _load()
    used = data.get("count", 0)
    limit = _detect_limit()
    remaining = max(0, limit - used)
    pct = min(100, used / limit * 100)
    return used, remaining, pct


def get_human_limit() -> str:
    lim = _detect_limit()
    return "unlimited" if lim >= 99999 else str(lim)
