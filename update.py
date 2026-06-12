from __future__ import annotations

import json
import os
import platform
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

import requests

from version import __version__

UPDATE_URL = "https://asknova.vercel.app/version.json"
TIMEOUT = 5

_SYSTEM = platform.system()


def _ver_tuple(v: str) -> tuple:
    return tuple(int(x) for x in v.split("."))


def _get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent


def check_for_update() -> dict:
    result = {"update_available": False, "version": __version__, "error": "", "download_url": ""}
    try:
        print("[Updater] Checking for updates...")
        r = requests.get(UPDATE_URL, timeout=TIMEOUT)
        r.raise_for_status()
        data = r.json()
        remote_ver = data.get("version", "")
        url_key = "download_url"
        remote_url = data.get(url_key, data.get("download_url", ""))
        if remote_ver and _ver_tuple(remote_ver) > _ver_tuple(__version__):
            result["update_available"] = True
            result["version"] = remote_ver
            result["download_url"] = remote_url
            print(f"[Updater] Update found: {__version__} -> {remote_ver}")
        else:
            print(f"[Updater] Already up-to-date ({__version__})")
    except requests.RequestException as e:
        result["error"] = str(e)
        print(f"[Updater] Check failed: {e}")
    except (json.JSONDecodeError, KeyError, ValueError) as e:
        result["error"] = str(e)
        print(f"[Updater] Bad response: {e}")
    return result


def check_for_update_async(callback=None) -> None:
    def _run():
        result = check_for_update()
        if callback:
            callback(result)
    threading.Thread(target=_run, daemon=True).start()


def download_to_temp(url: str) -> str:
    """Download a file to a temp dir and return the local path. Returns '' on failure."""
    try:
        print(f"[Updater] Downloading {url}")
        r = requests.get(url, timeout=120)
        r.raise_for_status()
        tmp_dir = Path(tempfile.mkdtemp(prefix="nova_update_"))
        path = tmp_dir / "Nova.exe"
        path.write_bytes(r.content)
        print(f"[Updater] Downloaded {path.stat().st_size // 1024 // 1024} MB")
        return str(path)
    except Exception as e:
        print(f"[Updater] Download failed: {e}")
        return ""


def apply_update(download_url: str = "") -> dict:
    result = {"ok": False, "error": ""}
    path = download_to_temp(download_url)
    if not path:
        result["error"] = "Download failed"
        return result
    return _apply_local(path)


def apply_local(path: str) -> dict:
    return _apply_local(path)


def _apply_local(path: str) -> dict:
    result = {"ok": False, "error": ""}
    base_dir = _get_base_dir()
    exe_path = Path(path)
    try:
        if _SYSTEM == "Windows":
            batch_path = base_dir / "_update.bat"
            old_dir = base_dir / "_old"
            batch_lines = [
                "@echo off",
                "title Nova Updater",
                "timeout /t 1 /nobreak >nul",
            ]
            if getattr(sys, "frozen", False):
                batch_lines.extend([
                    f'if exist "{old_dir}" rmdir /s /q "{old_dir}"',
                    f'mkdir "{old_dir}"',
                    f'move /y "{base_dir / "Nova.exe"}" "{old_dir / "Nova.exe"}" >nul 2>&1',
                    f'copy /y "{exe_path}" "{base_dir / "Nova.exe"}" >nul 2>&1',
                    f'if exist "{old_dir}" rmdir /s /q "{old_dir}" >nul 2>&1',
                    f':retry_rm',
                    f'if exist "{exe_path.parent}" (',
                    f'  rmdir /s /q "{exe_path.parent}" >nul 2>&1',
                    f'  if exist "{exe_path.parent}" (',
                    f'    timeout /t 1 /nobreak >nul',
                    f'    goto retry_rm',
                    f'  )',
                    f')',
                    f'start "" "{base_dir / "Nova.exe"}"',
                    "exit",
                ])
            else:
                batch_lines.extend([
                    f'copy /y "{exe_path}" "{base_dir / "Nova.exe"}" >nul 2>&1',
                    f':retry_rm',
                    f'if exist "{exe_path.parent}" (',
                    f'  rmdir /s /q "{exe_path.parent}" >nul 2>&1',
                    f'  if exist "{exe_path.parent}" (',
                    f'    timeout /t 1 /nobreak >nul',
                    f'    goto retry_rm',
                    f'  )',
                    f')',
                    f'start "" "{sys.executable}" "{base_dir / "main.py"}"',
                    "exit",
                ])
            batch_path.write_text("\n".join(batch_lines), encoding="utf-8")
            print("[Updater] Launching updater and exiting...")
            subprocess.Popen(
                ["cmd.exe", "/c", str(batch_path)],
                shell=True,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            sys.exit(0)

    except Exception as e:
        result["error"] = str(e)
        print(f"[Updater] Apply failed: {e}")
        return result
