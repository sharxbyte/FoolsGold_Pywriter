"""Filesystem locations and name validation."""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

from . import APP_NAME


def resource_dir() -> Path:
    """Folder containing bundled resources (works under PyInstaller too)."""
    base = getattr(sys, "_MEIPASS", None)
    if base:
        return Path(base) / "pywriter"
    return Path(__file__).resolve().parent


def packs_dir() -> Path:
    return resource_dir() / "packs"


def user_data_dir() -> Path:
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA") or Path.home())
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    d = base / APP_NAME
    d.mkdir(parents=True, exist_ok=True)
    return d


def models_dir() -> Path:
    d = user_data_dir() / "models"
    d.mkdir(parents=True, exist_ok=True)
    return d


def default_projects_dir() -> Path:
    docs = Path.home() / "Documents"
    base = docs if docs.exists() else Path.home()
    return base / "PyWriter Projects"


# --- Folder / file name validation -------------------------------------------------

_INVALID_CHARS = r'<>:"/\|?*'
_RESERVED = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


def validate_folder_name(name: str) -> str | None:
    """Return an error message, or None when the name is a legal folder name on
    Windows, macOS and Linux."""
    if not name or not name.strip():
        return "Please enter a title."
    if name != name.strip():
        return "The title can't start or end with a space."
    bad = sorted({c for c in name if c in _INVALID_CHARS or ord(c) < 32})
    if bad:
        shown = " ".join(repr(c)[1:-1] if ord(c) >= 32 else "control character" for c in bad)
        return f"The title can't contain these characters: {shown}"
    if name.endswith("."):
        return "The title can't end with a period."
    if name.split(".")[0].upper() in _RESERVED:
        return f"'{name}' is a reserved name on Windows. Please choose another."
    if len(name) > 120:
        return "Please keep the title under 120 characters."
    return None


def sanitize_folder_name(name: str) -> str:
    """Best-effort conversion of arbitrary text into a legal folder name."""
    cleaned = "".join("_" if (c in _INVALID_CHARS or ord(c) < 32) else c for c in name)
    cleaned = re.sub(r"\s+", " ", cleaned).strip().rstrip(".")
    if not cleaned:
        cleaned = "Untitled"
    if cleaned.split(".")[0].upper() in _RESERVED:
        cleaned = f"{cleaned}_project"
    return cleaned[:120]
