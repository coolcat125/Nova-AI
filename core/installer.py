"""Auto-dependency installer. Install pip packages on demand."""

import importlib
import subprocess
import sys


def ensure(package: str, import_name: str = None) -> bool:
    """Ensure a package is installed. Install it if missing. Returns True if available."""
    name = import_name or package.split("[")[0].split(">")[0].split("=")[0].strip()
    try:
        importlib.import_module(name)
        return True
    except ImportError:
        pass
    _pip_install(package)
    try:
        importlib.import_module(name)
        return True
    except ImportError:
        return False


def _pip_install(package: str) -> None:
    print(f"[Installer] Installing {package} ...")
    try:
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", "--quiet", package],
            timeout=120,
        )
        print(f"[Installer] OK  {package}")
    except Exception as e:
        print(f"[Installer] FAIL  {package}: {e}")


def ensure_many(packages: list[tuple[str, str]]) -> dict[str, bool]:
    """Ensure multiple packages. Each entry: (pip_package, import_name)."""
    results = {}
    for pkg, imp in packages:
        results[pkg] = ensure(pkg, imp)
    return results


def ensure_requirements(path: str) -> dict[str, bool]:
    """Install all packages from a requirements.txt file. Returns {pkg: ok}."""
    try:
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", "-r", path, "--quiet"],
            timeout=300,
        )
        return {}
    except subprocess.CalledProcessError as e:
        return {"requirements.txt": False}
