import os
import sys
import platform
from pathlib import Path


def get_bundle_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parent.parent


def get_data_dir() -> Path:
    if getattr(sys, "frozen", False):
        system = platform.system()
        if system == "Darwin":
            return Path.home() / "Library" / "Application Support" / "Nova"
        elif system == "Windows":
            return Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming")) / "Nova"
        else:
            return Path.home() / ".config" / "Nova"
    return Path(__file__).resolve().parent.parent
