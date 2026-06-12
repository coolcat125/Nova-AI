import os
import sys
import subprocess
import platform
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DIST_DIR = BASE_DIR / "dist"
SYSTEM   = platform.system()  # Windows / Darwin

IS_WIN = SYSTEM == "Windows"

HIDDEN_IMPORTS = [
    "google.genai",
    "google.genai.types",
    "openai",
    "plyer",
    "pyautogui",
    "mss",
    "pandas",
    "playwright",
    "psutil",
    "pyperclip",
    "PyPDF2",
    "pydub",
    "python_docx",
    "python_pptx",
    "send2trash",
    "sounddevice",
    "youtube_transcript_api",
    "PIL",
    "PIL.ImageDraw",
    "cv2",
    "numpy",
    "openpyxl",
    "pdfplumber",
    "dotenv",
    "duckduckgo_search",
    "providers",
    "providers.gemini",
    "providers.openai_provider",
    "providers.ollama",
    "providers.base",
    "actions.scheduler",
    "update",
    "version",
    "core.installer",
    "memory.config_manager",
    "requests",
]

if IS_WIN:
    HIDDEN_IMPORTS += [
        "pywinauto",
        "comtypes",
        "pycaw",
        "pygetwindow",
        "win10toast",
        "PIL._tkinter_finder",
        "psutil._psutil_windows",
    ]

if IS_WIN:
    EXCLUDE_MODULES = [
        "torch", "tensorflow", "transformers", "sklearn", "scipy",
        "sympy", "bitsandbytes", "onnxruntime", "torchaudio", "torchvision",
        "sqlalchemy", "bokeh", "matplotlib", "seaborn", "plotly",
        "jinja2", "sphinx", "notebook", "ipython", "jupyter",
    ]
else:
    EXCLUDE_MODULES = [
        "torch", "tensorflow", "transformers", "sklearn", "scipy",
        "sympy", "bitsandbytes", "onnxruntime", "torchaudio", "torchvision",
        "sqlalchemy", "bokeh", "matplotlib", "seaborn", "plotly",
        "jinja2", "sphinx", "notebook", "ipython", "jupyter",
        "pywinauto", "comtypes", "pycaw", "pygetwindow", "win10toast",
    ]

DATA_FILES = []

for pkg in ["providers", "config", "agent", "actions", "memory"]:
    src = BASE_DIR / pkg
    if src.exists():
        DATA_FILES.append(f"{src}{os.pathsep}{pkg}")

for fn in ["ui.py", "version.py", "update.py"]:
    if (BASE_DIR / fn).exists():
        DATA_FILES.append(f"{BASE_DIR / fn}{os.pathsep}.")

ICON_PATH = BASE_DIR / "icon.ico"
ICON_ARGS = [f"--icon={ICON_PATH}"] if ICON_PATH.exists() and IS_WIN else []

if ICON_PATH.exists():
    DATA_FILES.append(f"{ICON_PATH}{os.pathsep}.")

if (BASE_DIR / "core").exists():
    DATA_FILES.append(f"{BASE_DIR / 'core'}{os.pathsep}core")

WORKPATH = Path(os.environ.get("RUNNER_TEMP", Path(os.environ.get("TEMP", "C:/temp")))) / "nova-build"

OUTPUT_NAME = "Nova"

cmd = [
    sys.executable, "-m", "PyInstaller",
    "--onefile",
    "--windowed" if (IS_WIN or IS_MAC) else "--console",
    f"--name={OUTPUT_NAME}",
    f"--distpath={DIST_DIR}",
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
print(f"[Builder] {' '.join(cmd)}")
sys.stdout.flush()

result = subprocess.run(cmd, cwd=BASE_DIR)
if result.returncode != 0:
    print(f"[Builder] FAILED with code {result.returncode}")
    sys.exit(result.returncode)

if IS_WIN:
    out = DIST_DIR / "Nova.exe"
elif IS_MAC:
    out = DIST_DIR / "Nova"

if out.exists():
    size_mb = out.stat().st_size / (1024 * 1024)
    print(f"[Builder] OK  ->  {out}  ({size_mb:.1f} MB)")
else:
    print(f"[Builder] WARN: {out} not found in dist/")

if IS_MAC:
    print("[Builder] macOS builds are archived. Skipping DMG creation.")
