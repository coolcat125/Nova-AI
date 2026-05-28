import subprocess
import sys
from pathlib import Path

print("Installing requirements...")
subprocess.run([sys.executable, "-m", "pip", "install", "-r", "requirements.txt"], check=True)

print("Installing Playwright browsers...")
subprocess.run([sys.executable, "-m", "playwright", "install"], check=True)

env_path = Path(".env")
if not env_path.exists():
    key = input("\nPaste your Gemini API key (get one free at aistudio.google.com): ").strip()
    if key:
        env_path.write_text(f'GEMINI_API_KEY={key}\n')
        print("[OK] API key saved to .env")
    else:
        print("[WARN] No key entered. Create a .env file with GEMINI_API_KEY before running main.py")
else:
    print("[OK] .env already exists")

print("\n[OK] Setup complete! Run 'python main.py' to start Nova.")
