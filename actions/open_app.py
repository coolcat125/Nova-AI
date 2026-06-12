import time
import subprocess
import platform
import shutil

try:
    import psutil
    _PSUTIL = True
except ImportError:
    _PSUTIL = False

_SYSTEM = platform.system()

_APP_ALIASES: dict[str, str] = {
    "chrome":             "chrome",
    "google chrome":      "chrome",
    "firefox":            "firefox",
    "edge":               "msedge",
    "brave":              "brave",
    "safari":             "msedge",
    "opera":              "opera",
    "whatsapp":           "WhatsApp",
    "telegram":           "Telegram",
    "discord":            "Discord",
    "slack":              "Slack",
    "zoom":               "Zoom",
    "teams":              "msteams",
    "skype":              "skype",
    "signal":             "signal",
    "spotify":            "Spotify",
    "vlc":                "vlc",
    "netflix":            "Netflix",
    "vscode":             "code",
    "visual studio code": "code",
    "code":               "code",
    "terminal":           "wt",
    "cmd":                "cmd.exe",
    "powershell":         "powershell.exe",
    "postman":            "Postman",
    "git":                "git-bash",
    "figma":              "Figma",
    "blender":            "blender",
    "word":               "winword",
    "excel":              "excel",
    "powerpoint":         "powerpnt",
    "libreoffice":        "soffice",
    "notepad":            "notepad.exe",
    "textedit":           "notepad.exe",
    "explorer":           "explorer.exe",
    "file explorer":      "explorer.exe",
    "finder":             "explorer.exe",
    "task manager":       "taskmgr.exe",
    "settings":           "ms-settings:",
    "calculator":         "calc.exe",
    "paint":              "mspaint.exe",
    "instagram":          "Instagram",
    "tiktok":             "TikTok",
    "notion":             "Notion",
    "obsidian":           "Obsidian",
    "capcut":             "CapCut",
    "steam":              "steam",
    "epic":               "EpicGamesLauncher",
    "epic games":         "EpicGamesLauncher",
}


def _normalize(raw: str) -> str:
    key = raw.lower().strip()

    if key in _APP_ALIASES:
        return _APP_ALIASES[key]

    for alias_key, val in _APP_ALIASES.items():
        if alias_key in key or key in alias_key:
            return val

    return raw

def _launch_windows(app_name: str) -> bool:

    if shutil.which(app_name) or shutil.which(app_name.split(".")[0]):
        try:
            subprocess.Popen(
                app_name,
                shell=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            time.sleep(1.5)
            return True
        except Exception as e:
            print(f"[open_app] subprocess failed: {e}")

    if ":" in app_name:
        try:
            subprocess.Popen(f"start {app_name}", shell=True)
            time.sleep(1.0)
            return True
        except Exception:
            pass

    try:
        import pyautogui
        pyautogui.PAUSE = 0.1
        pyautogui.press("win")
        time.sleep(0.7)
        pyautogui.write(app_name, interval=0.05)
        time.sleep(0.9)
        pyautogui.press("enter")
        time.sleep(2.5)
        return True
    except Exception as e:
        print(f"[open_app] Start Menu search failed: {e}")

    return False


_OS_LAUNCHERS = {
    "Windows": _launch_windows,
}

def open_app(
    parameters=None,
    response=None,
    player=None,
    session_memory=None,
) -> str:
    app_name = (parameters or {}).get("app_name", "").strip()

    if not app_name:
        return "No application name provided."

    launcher = _OS_LAUNCHERS.get(_SYSTEM)
    if launcher is None:
        return f"Unsupported operating system: {_SYSTEM}"

    normalized = _normalize(app_name)
    print(f"[open_app] Launching: '{app_name}'  ->  '{normalized}' ({_SYSTEM})")

    if player:
        player.write_log(f"[open_app] {app_name}")

    try:
        if launcher(normalized):
            return f"Opened {app_name}."
        if normalized.lower() != app_name.lower():
            if launcher(app_name):
                return f"Opened {app_name}."
        return (
            f"Could not confirm that {app_name} launched. "
            f"It may still be loading, or it might not be installed."
        )
    except Exception as e:
        print(f"[open_app] Error: {e}")
        return f"Failed to open {app_name}: {e}"