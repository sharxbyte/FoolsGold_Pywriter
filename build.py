"""Build the standalone FoolsGold PyWriter app with Nuitka (a folder build, never one-file).

    python -m pip install -r requirements.txt -r requirements-build.txt
    python build.py                 # compile to dist/FoolsGoldPyWriter/ and run its self-test
    python build.py --installer     # ...then also build the Windows installer with Inno Setup

Nuitka compiles the Python code to C, so it needs a C compiler: on Windows, Visual Studio
(or the Build Tools) with "Desktop development with C++". If none is found Nuitka offers to
download MinGW64. The first build takes a long time (often 20-60 minutes); later builds are
faster because Nuitka caches compiled modules.

The output folder is what gets signed and packed into the installer:
    dist/FoolsGoldPyWriter/FoolsGoldPyWriter.exe   + DLLs, Qt plugins and data
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from pywriter import APP_DISPLAY_NAME, APP_VERSION  # noqa: E402

APP_EXE = "FoolsGoldPyWriter"
DIST = ROOT / "dist"
OUT = DIST / APP_EXE
PKG = ROOT / "pywriter"
WIN = os.name == "nt"

# Libraries other packages can drag in from a shared Python install that the app never uses.
NOT_USED = ["torch", "torchvision", "torchaudio", "scipy", "pandas", "matplotlib", "PIL", "tkinter",
            "IPython", "jupyter", "notebook", "sklearn", "tensorflow", "cv2", "sympy", "numba", "pytest",
            "setuptools", "pip", "piper.train", "onnxruntime.quantization", "onnxruntime.tools",
            "onnxruntime.transformers", "comtypes.test", "llama_cpp.server",
            "PyInstaller", "nuitka",
            # optional extras of llama-cpp / piper for Hugging Face downloads and chat formats PyWriter
            # doesn't use (it loads local GGUF files); left in, they made a 230 MB exe that Windows
            # couldn't stamp with its icon and version
            "transformers", "huggingface_hub", "hf_xet", "accelerate", "tokenizers", "safetensors",
            "openai", "aiohttp", "rich", "pygments", "pytesseract", "gguf", "fsspec", "piper.g2pw_onnx"]
# Optional at run time; included only if installed. Nuitka follows ordinary imports by itself.
# FORCE: packages that load parts of themselves dynamically (drivers, generated COM wrappers).
# DATA:  packages that ship DLLs or data files next to their code.
FORCE = ["pyttsx3", "pycaw", "comtypes"]
DATA = ["vosk", "llama_cpp", "piper", "onnxruntime"]


def version4() -> str:
    """1.0.1 -> 1.0.1.0 (Windows file versions have four parts; SignPath checks they match)."""
    return ".".join((APP_VERSION.split(".") + ["0", "0", "0"])[:4])


def nuitka_args() -> list[str]:
    version4_ = version4()
    args = [
        sys.executable, "-m", "nuitka", str(ROOT / "main.py"),
        "--standalone",                       # a folder build; never --onefile
        "--assume-yes-for-downloads",
        f"--output-dir={DIST}",
        f"--output-filename={APP_EXE}{'.exe' if WIN else ''}",
        "--enable-plugin=pyside6",
        "--include-qt-plugins=multimedia,texttospeech",
        "--include-package=pywriter",
        f"--include-data-dir={PKG / 'packs'}=pywriter/packs",
        f"--include-data-dir={PKG / 'resources'}=pywriter/resources",
        f"--include-data-dir={PKG / 'data'}=pywriter/data",
        "--noinclude-qt-translations",
        "--report=" + str(DIST / "nuitka-report.xml"),
    ]
    if WIN:
        args += [
            "--windows-console-mode=disable",
            f"--windows-icon-from-ico={PKG / 'resources' / 'Icon.ico'}",
            # file metadata (SignPath checks product name and version on every signed file)
            f"--product-name={APP_DISPLAY_NAME}",
            f"--product-version={version4_}",
            f"--file-version={version4_}",
            f"--file-description={APP_DISPLAY_NAME}",
            "--company-name=sharxbyte",
            "--copyright=Copyright (C) 2023-2026 sharxbyte. GPL-3.0-or-later.",
        ]
        if shutil.which("cl") or Path(r"C:\Program Files (x86)\Microsoft Visual Studio\Installer\vswhere.exe").exists():
            args.append("--msvc=latest")
    for mod in NOT_USED:
        args.append(f"--nofollow-import-to={mod}")
    import importlib.util
    for mod in FORCE + DATA:
        if importlib.util.find_spec(mod) is None:
            print(f"  (optional {mod} not installed - leaving it out)")
            continue
        if mod in FORCE:
            args.append(f"--include-package={mod}")
        if mod in DATA:
            args += [f"--include-module={mod}", f"--include-package-data={mod}"]
    return args


def copy_docs() -> None:
    # the license terms must travel with every copy
    for doc in ("LICENSE", "TERMS-OF-USE.md", "README.md"):
        shutil.copy2(ROOT / doc, OUT / doc)


def selftest() -> bool:
    exe = OUT / (APP_EXE + (".exe" if WIN else ""))
    report = DIST / "selftest.json"
    report.unlink(missing_ok=True)
    print(f"\nRunning the built app's self-test ({exe.name} --selftest)...")
    subprocess.run([str(exe), f"--selftest={report}"], timeout=600)
    if not report.exists():
        print("  self-test wrote no report: the app failed to start")
        return False
    r = json.loads(report.read_text(encoding="utf-8"))
    for c in r["checks"]:
        mark = "ok  " if c["ok"] else ("FAIL" if c["required"] else "warn")
        print(f"  [{mark}] {c['name']}: {c['detail'][:110]}")
    print("  SELF-TEST PASSED" if r["ok"] else "  SELF-TEST FAILED")
    return bool(r["ok"])


def build_installer() -> Path:
    iss = ROOT / "installer" / "FoolsGoldPyWriter.iss"
    candidates = [shutil.which("iscc"), r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
                  os.path.expandvars(r"%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"),
                  r"C:\Program Files\Inno Setup 6\ISCC.exe"]
    iscc = next((c for c in candidates if c and Path(c).exists()), None)
    if not iscc:
        sys.exit("Inno Setup 6 (ISCC.exe) not found. Install it from https://jrsoftware.org/isinfo.php "
                 "or:  winget install JRSoftware.InnoSetup")
    subprocess.run([iscc, f"/DAppVersion={APP_VERSION}", f"/DAppVersion4={version4()}", f"/DSourceDir={OUT}",
                    f"/DOutputDir={DIST}",
                    str(iss)], check=True)
    return DIST / f"FoolsGoldPyWriter-{APP_VERSION}-setup.exe"


def main() -> int:
    if "--print-version4" in sys.argv:  # used by CI
        print(version4())
        return 0
    if "--installer-only" not in sys.argv:
        if OUT.exists():
            shutil.rmtree(OUT)
        main_dist = DIST / "main.dist"
        if main_dist.exists():
            shutil.rmtree(main_dist)
        DIST.mkdir(exist_ok=True)
        subprocess.run(nuitka_args(), check=True)
        main_dist.rename(OUT)
        copy_docs()
        if not selftest():
            return 1
    if "--installer" in sys.argv or "--installer-only" in sys.argv:
        print("Installer:", build_installer())
    return 0


if __name__ == "__main__":
    sys.exit(main())
