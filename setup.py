import platform
import shutil
import subprocess
import sys
from pathlib import Path

system = platform.system()

print(f"Detected OS: {system}")

if system == "Linux":
    print("\n--- Linux System Dependencies ---")
    missing = []
    for cmd, pkg in [
        ("scrot", "scrot"),
        ("wmctrl", "wmctrl"),
        ("brightnessctl", "brightnessctl"),
        ("xdg-open", "xdg-utils"),
        ("pkg-config", "pkg-config"),
    ]:
        if not shutil.which(cmd):
            missing.append(pkg)
    try:
        import pyaudio
    except ImportError:
        missing.append("portaudio19-dev + python3-pyaudio")
    if missing:
        print("Missing system packages: " + ", ".join(missing))
        print("Install with:")
        print(f"  sudo apt install {' '.join(missing)}")
        try:
            ans = input("Continue anyway? [Y/n]: ").strip().lower()
        except (EOFError, OSError):
            ans = "y"
        if ans == "n":
            sys.exit(1)
    else:
        print("[OK] All Linux system packages found.")

print("Installing requirements...")
pip_args = [sys.executable, "-m", "pip", "install", "-r", "requirements.txt"]
if system == "Linux":
    pip_args.append("--break-system-packages")
subprocess.run(pip_args, check=True)

if system == "Windows":
    print("Installing Playwright Chromium browser...")
    try:
        subprocess.run(
            [sys.executable, "-m", "playwright", "install", "chromium"],
            timeout=300, check=True
        )
        print("[OK] Playwright Chromium installed")
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
        print(f"[WARN] Playwright install failed ({e}). Run 'python -m playwright install chromium' manually later.")
else:
    print("[SKIP] Playwright browser install skipped on non-Windows (use your system package manager or 'playwright install' if needed)")

env_path = Path(".env")
env_vars = {}

if env_path.exists():
    for line in env_path.read_text().strip().splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            env_vars[k.strip()] = v.strip()

print("\n--- Provider Setup ---")
print("Select your LLM provider:")
print("  1) Gemini (default) - requires GEMINI_API_KEY")
print("  2) OpenAI - requires OPENAI_API_KEY (works with OpenAI, Cerebras, Together, etc.)")
print("  3) Ollama - local models (no API key needed)")
choice = input("Choice [1]: ").strip() or "1"

if choice == "2":
    env_vars["LLM_PROVIDER"] = "openai"
    key = input("OpenAI API key (get one at platform.openai.com): ").strip()
    if key:
        env_vars["OPENAI_API_KEY"] = key
    base_url = input("Base URL (optional, for Cerebras/Together/etc. Leave blank for OpenAI): ").strip()
    if base_url:
        env_vars["OPENAI_BASE_URL"] = base_url
elif choice == "3":
    env_vars["LLM_PROVIDER"] = "ollama"
    url = input("Ollama base URL [http://localhost:11434/v1]: ").strip()
    if url:
        env_vars["OLLAMA_BASE_URL"] = url
    else:
        env_vars["OLLAMA_BASE_URL"] = "http://localhost:11434/v1"
else:
    env_vars["LLM_PROVIDER"] = "gemini"
    if "GEMINI_API_KEY" not in env_vars:
        key = input("\nPaste your Gemini API key (get one free at aistudio.google.com): ").strip()
        if key:
            env_vars["GEMINI_API_KEY"] = key

lines = [f"{k}={v}" for k, v in env_vars.items()]
env_path.write_text("\n".join(lines) + "\n")
print(f"[OK] .env saved with {len(env_vars)} variable(s)")

print("\n[OK] Setup complete! Run 'python main.py' to start Nova.")
