import os
import sys
import time
import subprocess
import platform
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DIST_DIR = BASE_DIR / "dist"
SYSTEM   = platform.system()

IS_WIN = SYSTEM == "Windows"
IS_MAC = SYSTEM == "Darwin"

HIDDEN_IMPORTS = [
    "google.genai", "google.genai.types", "openai", "plyer", "pyautogui",
    "mss", "pandas", "playwright", "psutil", "pyperclip", "PyPDF2", "pydub",
    "python_docx", "python_pptx", "send2trash", "sounddevice",
    "youtube_transcript_api", "PIL", "PIL.ImageDraw", "cv2", "numpy",
    "openpyxl", "pdfplumber", "dotenv", "duckduckgo_search", "providers",
    "providers.gemini", "providers.openai_provider", "providers.ollama",
    "providers.base", "actions.scheduler", "update", "version",
    "core.installer", "memory.config_manager", "requests",
    "supabase",
]

if IS_WIN:
    HIDDEN_IMPORTS += [
        "pywinauto", "comtypes", "pycaw", "pygetwindow", "win10toast",
        "PIL._tkinter_finder", "psutil._psutil_windows",
    ]

EXCLUDE_MODULES = [
    "torch", "tensorflow", "transformers", "sklearn", "scipy",
    "sympy", "bitsandbytes", "onnxruntime", "torchaudio", "torchvision",
    "sqlalchemy", "bokeh", "matplotlib", "seaborn", "plotly",
    "jinja2", "sphinx", "notebook", "ipython", "jupyter",
]
if not IS_WIN:
    EXCLUDE_MODULES += ["pywinauto", "comtypes", "pycaw", "pygetwindow", "win10toast"]

DATA_FILES = []

for pkg in ["providers", "config", "agent", "actions", "memory"]:
    src = BASE_DIR / pkg
    if src.exists():
        DATA_FILES.append(f"{src}{os.pathsep}{pkg}")

for fn in ["ui.py", "version.py", "update.py"]:
    if (BASE_DIR / fn).exists():
        DATA_FILES.append(f"{BASE_DIR / fn}{os.pathsep}.")

if IS_MAC:
    ICON_PATH = BASE_DIR / "assets" / "nova.icns"
    if not ICON_PATH.exists():
        ICON_PATH = BASE_DIR / "icon.ico"
else:
    ICON_PATH = BASE_DIR / "icon.ico"
ICON_ARGS = [f"--icon={ICON_PATH}"] if ICON_PATH.exists() else []

if (BASE_DIR / "icon.ico").exists():
    DATA_FILES.append(f"{BASE_DIR / 'icon.ico'}{os.pathsep}.")

if (BASE_DIR / "core").exists():
    DATA_FILES.append(f"{BASE_DIR / 'core'}{os.pathsep}core")

_tmp = os.environ.get("RUNNER_TEMP") or os.environ.get("TEMP") or "/tmp"
LOCAL_TMP = Path("/tmp")  # local filesystem, not pCloud
WORKPATH = LOCAL_TMP / "nova-build"

OUTPUT_NAME = "Nova"

if IS_MAC:
    BUNDLE_MODE = "--onedir"
else:
    BUNDLE_MODE = "--onefile"

LOCAL_DIST = LOCAL_TMP / "nova-dist"

cmd = [
    sys.executable, "-m", "PyInstaller",
    BUNDLE_MODE,
    "--windowed" if (IS_WIN or IS_MAC) else "--console",
    f"--name={OUTPUT_NAME}",
    f"--distpath={LOCAL_DIST}",
    f"--workpath={WORKPATH}",
    "--clean",
    "--noconfirm",
] + ICON_ARGS

for mod in EXCLUDE_MODULES:
    cmd.append(f"--exclude-module={mod}")

for mod in HIDDEN_IMPORTS:
    cmd.append(f"--hidden-import={mod}")

for df in DATA_FILES:
    cmd.append(f"--add-data={df}")

cmd.append(str(BASE_DIR / "main.py"))

print(f"[Builder] Platform: {SYSTEM}")
print("[Builder] Running PyInstaller...")
sys.stdout.flush()

result = subprocess.run(cmd, cwd=BASE_DIR)
if result.returncode != 0:
    print(f"[Builder] FAILED with code {result.returncode}")
    sys.exit(result.returncode)

if IS_WIN:
    out = LOCAL_DIST / "Nova.exe"
elif IS_MAC:
    out = LOCAL_DIST / "Nova.app"
else:
    out = LOCAL_DIST / "Nova"

if not out.exists():
    print(f"[Builder] WARN: {out} not found in dist/")
    sys.exit(1)

size_mb = out.stat().st_size / (1024 * 1024)
is_dir = " (directory)" if out.is_dir() else ""
print(f"[Builder] OK  ->  {out}  ({size_mb:.1f} MB){is_dir}")

if IS_MAC and out.is_dir():
    import plistlib
    plist_path = out / "Contents" / "Info.plist"
    if plist_path.exists():
        with open(plist_path, "rb") as f:
            plist = plistlib.load(f)
        plist["NSMicrophoneUsageDescription"] = "Nova needs microphone access for voice commands and conversation."
        with open(plist_path, "wb") as f:
            plistlib.dump(plist, f)
        print("[Builder] Added NSMicrophoneUsageDescription to Info.plist")
    subprocess.run(["codesign", "--force", "-s", "-", str(out)], check=True, capture_output=True)
    print("[Builder] Re-signed with ad-hoc signature after plist update")

if IS_MAC:
    import shutil
    DMG_WORK = LOCAL_TMP / "Nova-dmg"
    if DMG_WORK.exists():
        shutil.rmtree(DMG_WORK)
    DMG_WORK.mkdir(parents=True, exist_ok=True)

    app_dest = DMG_WORK / "Nova.app"
    subprocess.run(["ditto", str(out), str(app_dest)], check=True)
    (DMG_WORK / "Applications").symlink_to("/Applications")

    # Fix CFBundleIconFile (should be name without extension)
    # Do NOT re-sign after plist change — ad-hoc re-sign corrupts bundle
    plist_path = app_dest / "Contents" / "Info.plist"
    if plist_path.exists():
        import plistlib
        plist = plistlib.load(plist_path.open("rb"))
        plist["CFBundleIconFile"] = "nova"
        plist["CFBundleVersion"] = "1.0.0"
        plistlib.dump(plist, plist_path.open("wb"))

    # Copy background image into DMG (will hide it after AppleScript)
    bg_img = BASE_DIR / "assets" / "dmg-background.png"
    if bg_img.exists():
        shutil.copy2(str(bg_img), str(DMG_WORK / "background.png"))

    dmg_final = LOCAL_TMP / "Nova.dmg"
    env = os.environ.copy()
    env["TMPDIR"] = "/tmp"

    # Build staging DMG (read/write for customization)
    dmg_rw = LOCAL_TMP / "Nova-rw.dmg"
    subprocess.run(
        ["hdiutil", "create", "-volname", "Nova", "-srcfolder", str(DMG_WORK),
         "-ov", "-format", "UDRW", str(dmg_rw)],
        check=True, env=env)

    # Detach stale mounts and attach
    subprocess.run(["hdiutil", "detach", "/Volumes/Nova", "-quiet", "-force"], env=env)
    result = subprocess.run(["hdiutil", "attach", str(dmg_rw), "-noverify", "-noautoopen"],
                            capture_output=True, text=True, check=True, env=env)
    # Parse mount point from output
    vol_name = [line.split()[-1] for line in result.stdout.strip().split("\n") if "/Volumes/" in line][0]
    print(f"[Builder] DMG mounted at {vol_name}")

    time.sleep(1)


    osa = f'''
tell application "Finder"
  tell disk "{vol_name.split("/")[-1]}"
    open
    set current view of container window to icon view
    set toolbar visible of container window to false
    set statusbar visible of container window to false
    set the bounds of container window to {{100, 200, 600, 460}}
    set viewOptions to the icon view options of container window
    set arrangement of viewOptions to not arranged
    set icon size of viewOptions to 80
    set background picture of viewOptions to file "background.png"
    set position of item "Nova.app" of container window to {{130, 130}}
    set position of item "Applications" of container window to {{370, 130}}
    close
  end tell
end tell'''
    subprocess.run(["osascript", "-e", osa], check=True)

    # Hide the background file inside the DMG
    subprocess.run(["chflags", "hidden", f"{vol_name}/background.png"], check=True)

    subprocess.run(["hdiutil", "detach", vol_name], check=True, env=env)

    # Convert to compressed ULFO (LZFSE — better than UDZO)
    subprocess.run(
        ["hdiutil", "convert", str(dmg_rw), "-format", "ULFO",
         "-o", str(LOCAL_TMP / "Nova-converted")],
        check=True, env=env)

    (LOCAL_TMP / "Nova-converted.dmg").rename(dmg_final)
    shutil.rmtree(DMG_WORK)

    DIST_DIR.mkdir(parents=True, exist_ok=True)
    shutil.copy2(str(dmg_final), str(DIST_DIR / "Nova.dmg"))

    dmg_size = (DIST_DIR / "Nova.dmg").stat().st_size / (1024 * 1024)
    print(f"[Builder] DMG -> {DIST_DIR / 'Nova.dmg'} ({dmg_size:.1f} MB)")
    dmg_final.unlink(missing_ok=True)
    dmg_rw.unlink(missing_ok=True)
else:
    import shutil
    dest = DIST_DIR / out.name
    if dest.exists():
        shutil.rmtree(dest) if dest.is_dir() else dest.unlink()
    shutil.move(str(out), str(DIST_DIR))
    print(f"[Builder] Moved -> {DIST_DIR / out.name}")
