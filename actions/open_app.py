import os
import subprocess
import sys
import time
from pathlib import Path

_SYSTEM = sys.platform

_APP_DB: dict[str, dict[str, str]] = {
    "chrome":             {"win32": "chrome",        "darwin": "Google Chrome",       "linux": "google-chrome"},
    "google chrome":      {"win32": "chrome",        "darwin": "Google Chrome",       "linux": "google-chrome"},
    "firefox":            {"win32": "firefox",       "darwin": "Firefox",             "linux": "firefox"},
    "edge":               {"win32": "msedge",        "darwin": "Microsoft Edge",      "linux": "microsoft-edge"},
    "brave":              {"win32": "brave",         "darwin": "Brave Browser",       "linux": "brave-browser"},
    "safari":             {"win32": "msedge",        "darwin": "Safari",              "linux": "firefox"},
    "opera":              {"win32": "opera",         "darwin": "Opera",               "linux": "opera"},
    "whatsapp":           {"win32": "WhatsApp",      "darwin": "WhatsApp",            "linux": "whatsapp"},
    "telegram":           {"win32": "Telegram",      "darwin": "Telegram",            "linux": "telegram"},
    "discord":            {"win32": "Discord",       "darwin": "Discord",             "linux": "discord"},
    "slack":              {"win32": "Slack",         "darwin": "Slack",               "linux": "slack"},
    "zoom":               {"win32": "Zoom",          "darwin": "zoom.us",             "linux": "zoom"},
    "teams":              {"win32": "msteams",       "darwin": "Microsoft Teams",     "linux": "teams"},
    "skype":              {"win32": "skype",         "darwin": "Skype",               "linux": "skype"},
    "signal":             {"win32": "signal",        "darwin": "Signal",              "linux": "signal"},
    "spotify":            {"win32": "Spotify",       "darwin": "Spotify",             "linux": "spotify"},
    "vlc":                {"win32": "vlc",           "darwin": "VLC",                 "linux": "vlc"},
    "netflix":            {"win32": "Netflix",       "darwin": "Netflix",             "linux": "firefox"},
    "vscode":             {"win32": "code",          "darwin": "Visual Studio Code",  "linux": "code"},
    "visual studio code": {"win32": "code",          "darwin": "Visual Studio Code",  "linux": "code"},
    "code":               {"win32": "code",          "darwin": "Visual Studio Code",  "linux": "code"},
    "terminal":           {"win32": "wt",            "darwin": "Terminal",            "linux": "gnome-terminal"},
    "cmd":                {"win32": "cmd.exe",       "darwin": "Terminal",            "linux": "bash"},
    "powershell":         {"win32": "powershell.exe","darwin": "Terminal",            "linux": "bash"},
    "postman":            {"win32": "Postman",       "darwin": "Postman",             "linux": "postman"},
    "git":                {"win32": "git-bash",      "darwin": "Terminal",            "linux": "bash"},
    "figma":              {"win32": "Figma",         "darwin": "Figma",               "linux": "figma"},
    "blender":            {"win32": "blender",       "darwin": "Blender",             "linux": "blender"},
    "word":               {"win32": "winword",       "darwin": "Microsoft Word",      "linux": "libreoffice --writer"},
    "excel":              {"win32": "excel",         "darwin": "Microsoft Excel",     "linux": "libreoffice --calc"},
    "powerpoint":         {"win32": "powerpnt",      "darwin": "Microsoft PowerPoint","linux": "libreoffice --impress"},
    "libreoffice":        {"win32": "soffice",       "darwin": "LibreOffice",         "linux": "libreoffice"},
    "notepad":            {"win32": "notepad.exe",   "darwin": "TextEdit",            "linux": "gedit"},
    "textedit":           {"win32": "notepad.exe",   "darwin": "TextEdit",            "linux": "gedit"},
    "explorer":           {"win32": "explorer.exe",  "darwin": "Finder",              "linux": "nautilus"},
    "file explorer":      {"win32": "explorer.exe",  "darwin": "Finder",              "linux": "nautilus"},
    "finder":             {"win32": "explorer.exe",  "darwin": "Finder",              "linux": "nautilus"},
    "task manager":       {"win32": "taskmgr.exe",   "darwin": "Activity Monitor",    "linux": "gnome-system-monitor"},
    "settings":           {"win32": "ms-settings:",  "darwin": "System Preferences",  "linux": "gnome-control-center"},
    "calculator":         {"win32": "calc.exe",      "darwin": "Calculator",          "linux": "gnome-calculator"},
    "paint":              {"win32": "mspaint.exe",   "darwin": "Preview",             "linux": "gimp"},
    "instagram":          {"win32": "Instagram",     "darwin": "Instagram",           "linux": "firefox"},
    "tiktok":             {"win32": "TikTok",        "darwin": "TikTok",              "linux": "firefox"},
    "notion":             {"win32": "Notion",        "darwin": "Notion",              "linux": "notion"},
    "obsidian":           {"win32": "Obsidian",      "darwin": "Obsidian",            "linux": "obsidian"},
    "capcut":             {"win32": "CapCut",        "darwin": "CapCut",              "linux": "capcut"},
    "steam":              {"win32": "steam",         "darwin": "Steam",               "linux": "steam"},
    "epic":               {"win32": "EpicGamesLauncher", "darwin": "Epic Games Launcher", "linux": "legendary"},
    "epic games":         {"win32": "EpicGamesLauncher", "darwin": "Epic Games Launcher", "linux": "legendary"},
}


def _resolve_name(raw: str) -> str:
    lookup = raw.lower().strip()

    if lookup in _APP_DB:
        return _APP_DB[lookup].get(_SYSTEM, raw)

    for key, platforms in _APP_DB.items():
        if key in lookup or lookup in key:
            return platforms.get(_SYSTEM, raw)

    return raw


def _try_direct(name: str) -> bool:
    import shutil as _shutil
    if _shutil.which(name) or _shutil.which(name.split(".")[0]):
        try:
            subprocess.Popen(
                [name],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            time.sleep(1.5)
            return True
        except OSError:
            return False
    return False


def _start_menu_search(name: str) -> bool:
    try:
        import pyautogui
        pyautogui.PAUSE = 0.1
        pyautogui.press("win")
        time.sleep(0.7)
        pyautogui.write(name, interval=0.05)
        time.sleep(0.9)
        pyautogui.press("enter")
        time.sleep(2.5)
        return True
    except Exception:
        return False


def _win_launch(name: str) -> bool:
    if _try_direct(name):
        return True

    if ":" in name:
        try:
            subprocess.Popen(["cmd", "/c", "start", "", name])
            time.sleep(1.0)
            return True
        except OSError:
            pass

    return _start_menu_search(name)


def _mac_launch(name: str) -> bool:
    import shutil as _shutil

    for attempt in (name, f"{name}.app"):
        try:
            result = subprocess.run(
                ["open", "-a", attempt],
                capture_output=True, timeout=8,
            )
            if result.returncode == 0:
                time.sleep(1.0)
                return True
        except (OSError, subprocess.TimeoutExpired):
            continue

    binary = _shutil.which(name) or _shutil.which(name.lower())
    if binary:
        try:
            subprocess.Popen(
                [binary],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            time.sleep(1.0)
            return True
        except OSError:
            pass

    try:
        import pyautogui
        pyautogui.hotkey("command", "space")
        time.sleep(0.6)
        pyautogui.write(name, interval=0.05)
        time.sleep(0.8)
        pyautogui.press("enter")
        time.sleep(1.5)
        return True
    except Exception:
        return False


def _linux_launch(name: str) -> bool:
    import shutil as _shutil

    for variant in (
        name,
        name.lower(),
        name.lower().replace(" ", "-"),
        name.lower().replace(" ", "_"),
    ):
        found = _shutil.which(variant)
        if found:
            try:
                subprocess.Popen(
                    [found],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                )
                time.sleep(1.0)
                return True
            except OSError:
                continue

    try:
        subprocess.run(
            ["xdg-open", name],
            capture_output=True, timeout=5,
        )
        return True
    except (OSError, subprocess.TimeoutExpired):
        pass

    for slug in (
        name.lower(),
        name.lower().replace(" ", "-"),
        name.lower().replace(" ", ""),
    ):
        try:
            result = subprocess.run(
                ["gtk-launch", slug],
                capture_output=True, timeout=5,
            )
            if result.returncode == 0:
                return True
        except (OSError, subprocess.TimeoutExpired):
            continue

    return False


_LAUNCHERS = {
    "win32":  _win_launch,
    "darwin": _mac_launch,
    "linux":  _linux_launch,
}


def open_app(parameters: dict, speak=None) -> str:
    target = (parameters or {}).get("app_name", "").strip()

    if not target:
        return "No application name provided."

    dispatch = _LAUNCHERS.get(_SYSTEM)
    if dispatch is None:
        return f"Unsupported operating system: {_SYSTEM}"

    resolved = _resolve_name(target)
    print(f"[open_app] {target} -> {resolved} ({_SYSTEM})")

    try:
        if dispatch(resolved):
            return f"Opened {target}."

        if resolved.lower() != target.lower() and dispatch(target):
            return f"Opened {target}."

        return (
            f"Could not confirm that {target} launched. "
            f"It may still be loading, or it might not be installed."
        )
    except Exception as exc:
        print(f"[open_app] Error: {exc}")
        return f"Failed to open {target}: {exc}"
