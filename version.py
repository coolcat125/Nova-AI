import platform

VERSIONS: dict[str, str] = {
    "windows": "4.0.0",
    "macos": "1.0.0",
    "linux": "1.0.0",
}

_SYS = platform.system()
__version__ = (
    VERSIONS["windows"]
    if _SYS == "Windows"
    else VERSIONS["macos"]
    if _SYS == "Darwin"
    else VERSIONS["linux"]
)
