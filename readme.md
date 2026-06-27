# Nova 🌌
> Prompt Once. It Finishes.

![Windows](https://img.shields.io/badge/Windows-0078D6?style=for-the-badge&logo=windows&logoColor=white)
![macOS](https://img.shields.io/badge/macOS-000000?style=for-the-badge&logo=apple&logoColor=white)

Nova is a single-prompt autonomous desktop AI agent with always-on voice, live screen vision, and 19 built-in tools. Powered by Google Gemini native audio — no STT/TTS pipeline.

*Built on the groundwork of **FaithMakes** original vision.*

[![Nova Demo](https://img.youtube.com/vi/UuhD9J_L0uE/maxresdefault.jpg)](https://youtu.be/UuhD9J_L0uE)

---

## Features
- 🎙️ Always-listening voice — no wake word
- 👁️ Live screen vision
- 🖥️ Desktop & file automation
- 🌐 Browser control
- 💾 Long-term memory
- 🔧 19 built-in tools — no plugins needed
- 🔁 Self-healing — retries until done

---

## Requirements
- **OS:** Windows 10/11 or macOS
- **Python:** 3.12
- **Microphone:** Required for voice interaction
- **API Key:** Free Gemini API key (get one at aistudio.google.com)

---

## Setup

### Windows
```powershell
git clone https://github.com/coolcat125/nova.git
cd nova
pip install -r requirements.txt
playwright install
python main.py
```

### macOS (frozen DMG)
1. Download `Nova.dmg` from [GitHub Releases](https://github.com/coolcat125/Nova-AI/releases)
2. Double-click to mount, drag `Nova.app` to Applications
3. **Gatekeeper workaround** (unsigned app — Apple Developer account needed to fix):
   - **Right-click** `Nova.app` → **Open** (instead of double-click)
   - Or run: `xattr -rd com.apple.quarantine /Applications/Nova.app`

### From source (any OS)
```bash
git clone https://github.com/coolcat125/nova.git
cd nova
pip install -r requirements.txt
playwright install
python main.py
```

> ⚠️ If you hit a `ModuleNotFoundError`, just `pip install <module_name>` for that package.

---

## Discord
Questions, bugs, showcase: [discord.gg/NPp7SPvrNc](https://discord.gg/NPp7SPvrNc)

---

## 📄 License
Licensed under the **[MIT License](LICENSE)**.

⭐ **Star the repository to support the project.**
