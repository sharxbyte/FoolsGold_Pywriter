"""Build a standalone FoolsGold PyWriter app with PyInstaller.

    python -m pip install pyinstaller
    python build.py

Output: dist/FoolsGoldPyWriter/ (a folder build starts faster than --onefile).
"""
import os
import sys
from pathlib import Path

import PyInstaller.__main__

ROOT = Path(__file__).resolve().parent
SEP = ";" if os.name == "nt" else ":"
pkg = ROOT / "pywriter"

args = [
    str(ROOT / "main.py"),
    "--name=FoolsGoldPyWriter",
    "--noconfirm",
    "--windowed",
    f"--icon={pkg / 'resources' / 'Icon.ico'}",
    f"--add-data={pkg / 'packs'}{SEP}pywriter/packs",
    f"--add-data={pkg / 'resources'}{SEP}pywriter/resources",
    f"--add-data={pkg / 'data'}{SEP}pywriter/data",
    "--collect-all=vosk",
    "--hidden-import=PySide6.QtTextToSpeech",
]
for optional in ("piper", "onnxruntime", "jellyfish", "networkx"):
    try:
        __import__(optional)
        args.append(f"--collect-all={optional}")
    except ImportError:
        pass

if __name__ == "__main__":
    PyInstaller.__main__.run(args + sys.argv[1:])
