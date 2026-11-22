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
    "--hidden-import=networkx",
]
# Big libraries that other packages can drag in from a shared Python install but the
# app never uses (torch alone is ~540 MB).
for unused in ("torch", "torchvision", "torchaudio", "scipy", "pandas", "matplotlib", "PIL", "tkinter",
               "IPython", "jupyter", "notebook", "sklearn", "tensorflow", "cv2", "sympy", "numba",
               "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.Qt3DCore", "PySide6.QtQuick",
               "PySide6.QtQml", "PySide6.QtCharts", "PySide6.QtDataVisualization", "PySide6.QtPdf"):
    args.append(f"--exclude-module={unused}")
for optional in ("piper", "onnxruntime", "jellyfish"):
    try:
        __import__(optional)
        args.append(f"--collect-all={optional}")
    except ImportError:
        pass

if __name__ == "__main__":
    PyInstaller.__main__.run(args + sys.argv[1:])
