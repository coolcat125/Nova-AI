import platform
import shutil
import subprocess
import sys
from pathlib import Path


def _check_linux_deps():
    """Check for required Linux system packages."""
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
        import pyaudio  # noqa: F401
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


def _install_requirements():
    """Install Python packages from requirements.txt."""
    print("Installing requirements...")
    args = [sys.executable, "-m", "pip", "install", "-r", "requirements.txt"]
    if platform.system() == "Linux":
        args.append("--break-system-packages")
    subprocess.run(args, check=True)


def _install_playwright():
    """Install Playwright Chromium on Windows."""
    if platform.system() != "Windows":
        print("[SKIP] Playwright browser install skipped on non-Windows")
        return
    print("Installing Playwright Chromium browser...")
    try:
        subprocess.run(
            [sys.executable, "-m", "playwright", "install", "chromium"],
            timeout=300,
            check=True,
        )
        print("[OK] Playwright Chromium installed")
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
        print(f"[WARN] Playwright install failed ({e}). Run 'python -m playwright install chromium' manually later.")


def _read_env() -> dict[str, str]:
    """Read defaults.env as base, then override with .env if it exists."""
    env_vars: dict[str, str] = {}
    for path in [Path("defaults.env"), Path(".env")]:
        if path.exists():
            for line in path.read_text(encoding="utf-8").strip().splitlines():
                if "=" in line and not line.startswith("#"):
                    k, v = line.split("=", 1)
                    env_vars[k.strip()] = v.strip()
    return env_vars


def _write_env(env_vars: dict[str, str]):
    """Write env vars to .env file."""
    lines = [f"{k}={v}" for k, v in env_vars.items()]
    Path(".env").write_text("\n".join(lines) + "\n")
    print(f"[OK] .env saved with {len(env_vars)} variable(s)")


def _configure_provider(env_vars: dict[str, str]) -> dict[str, str]:
    """Interactive provider selection and API key setup."""
    print("\n--- Provider Setup ---")
    print("Select your LLM provider:")
    print("  1) Gemini (default) - requires GEMINI_API_KEY")
    print("  2) OpenAI - requires OPENAI_API_KEY (works with OpenAI, Cerebras, Together, etc.)")
    print("  3) OpenCode - requires OPENCODE_API_KEY (free models available)")
    print("  4) Ollama - local models (no API key needed)")
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
        env_vars["LLM_PROVIDER"] = "opencode"
        key = input("OpenCode API key (get one at opencode.ai/zen): ").strip()
        if key:
            env_vars["OPENCODE_API_KEY"] = key
        model = input("Model name [big-pickle]: ").strip()
        if model:
            env_vars["LLM_MODEL"] = model

    elif choice == "4":
        env_vars["LLM_PROVIDER"] = "ollama"
        url = input("Ollama base URL [http://localhost:11434/v1]: ").strip()
        url = url or "http://localhost:11434/v1"
        if "localhost" not in url and "127.0.0.1" not in url:
            print("WARNING: Non-localhost Ollama URL. Ensure Ollama is configured with TLS.")
        env_vars["OLLAMA_BASE_URL"] = url

    else:
        env_vars["LLM_PROVIDER"] = "gemini"
        if "GEMINI_API_KEY" not in env_vars:
            key = input("\nPaste your Gemini API key (get one free at aistudio.google.com): ").strip()
            if key:
                env_vars["GEMINI_API_KEY"] = key

    return env_vars


def main():
    system = platform.system()
    print(f"Detected OS: {system}")

    if system == "Linux":
        _check_linux_deps()

    _install_requirements()
    _install_playwright()

    env_vars = _read_env()
    env_vars = _configure_provider(env_vars)
    _write_env(env_vars)

    print("\n[OK] Setup complete! Run 'python main.py' to start Nova.")


if __name__ == "__main__":
    main()
