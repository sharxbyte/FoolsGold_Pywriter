"""Headless self-test for frozen builds:  FoolsGoldPyWriter.exe --selftest=report.json

Opens no windows and touches no user settings or projects. It checks that the
bundled data and every library the app relies on load in the built program, then
runs a small project through the interview engine, Talk mode, export, backup and
the main window (off-screen). Exit code 0 means every check passed. CI runs this on
the build before it is signed and packaged.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import traceback
from pathlib import Path


def run(report_path: str | None) -> int:
    tmp = Path(tempfile.mkdtemp(prefix="pywriter-selftest-"))
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    os.environ["PYWRITER_SETTINGS"] = str(tmp / "settings.ini")
    checks: list[dict] = []

    def check(name: str, fn, required: bool = True) -> None:
        try:
            detail = fn()
            checks.append({"name": name, "ok": True, "required": required, "detail": str(detail or "")})
        except Exception as e:  # noqa: BLE001 - every failure is reported, none is fatal
            checks.append({"name": name, "ok": False, "required": required,
                           "detail": f"{type(e).__name__}: {e}", "trace": traceback.format_exc()[-1500:]})

    from . import APP_VERSION
    from .paths import packs_dir, resource_dir

    def data_files():
        need = [packs_dir() / "flows.yaml", resource_dir() / "resources" / "Icon.ico",
                resource_dir() / "resources" / "splash.png", resource_dir() / "data" / "names_first.tsv",
                resource_dir() / "data" / "names_last.tsv"]
        missing = [str(p) for p in need if not p.exists()]
        if missing:
            raise FileNotFoundError(", ".join(missing))
        return f"{len(list(packs_dir().glob('*.yaml')))} pack files"

    def packs():
        from .library import Library
        lib = Library()
        if lib.errors:
            raise ValueError("; ".join(lib.errors))
        return f"{len(lib.packs)} packs"

    check("bundled data files", data_files)
    check("question packs load", packs)

    def imp(mod: str, attr: str | None = None):
        def f():
            m = __import__(mod, fromlist=["_"])
            if attr:
                getattr(m, attr)
            return getattr(m, "__version__", "") or "ok"
        return f

    for mod, attr, req in [("numpy", "array", True), ("yaml", "safe_load", True), ("docx", "Document", True),
                           ("PySide6.QtTextToSpeech", "QTextToSpeech", True),
                           ("vosk", "Model", True), ("sounddevice", "query_devices", True),
                           ("soundfile", "write", False), ("jellyfish", "jaro_winkler_similarity", False),
                           ("networkx", "spring_layout", True), ("pyttsx3", "init", False),
                           ("onnxruntime", "InferenceSession", False), ("piper", "PiperVoice", False),
                           ("llama_cpp", "Llama", False)] + \
            ([("comtypes", None, False), ("pycaw.pycaw", "AudioUtilities", False)] if os.name == "nt" else []):
        check(f"import {mod}", imp(mod, attr), required=req)

    def piper_speaks():
        from .voice import piper_dir, piper_installed
        voices = piper_installed()
        if not voices:
            return "no Piper voice installed - skipped"
        from piper import PiperVoice
        v = PiperVoice.load(str(piper_dir() / f"{voices[0]}.onnx"))
        samples = sum(len(c.audio_int16_array) for c in v.synthesize("Testing one two three."))
        if samples < 1000:
            raise AssertionError(f"only {samples} samples")
        return f"{voices[0]}: {samples} samples"

    check("Piper voice synthesis", piper_speaks, required=False)

    def workflow():
        from .backup import BackupManager
        from .engine import Interview, effective_fields
        from .export import export_story_bible
        from .library import Library
        from .nlu import Interpreter
        from .store import ProjectStore
        lib = Library()
        s = ProjectStore.create(tmp / "Selftest", "Selftest", "Fiction")
        iv = Interview(lib.pack_for_kind("character", "Fiction"), s)
        for value in ("Mara Venn", "primary"):
            iv.answer(value)
            iv.commit()
            iv.next()
        n = Interpreter(s, lib)
        for line in ("Mara has red hair and lives in Port Vell.", "Tomas is Mara's brother.", "character", "minor"):
            n.handle(line)
        m = s.find_by_name("Mara Venn")
        f = effective_fields(s, lib, m)
        if "Port Vell" not in f.get("home", "") or "Tomas" not in f.get("siblings", ""):
            raise AssertionError(f"Talk -> interview mismatch: {f.get('home')!r} {f.get('siblings')!r}")
        export_story_bible(s, lib)
        from .exporters import export_backup_zip
        z = export_backup_zip(s, lib, tmp / "backup.zip")
        import zipfile
        names = zipfile.ZipFile(z).namelist()
        if not any(n.endswith(".docx") for n in names) or not any(n.endswith(".csv") for n in names):
            raise AssertionError(f"backup zip incomplete: {names}")
        if not BackupManager(s).snapshot("selftest", force=True):
            raise AssertionError("no snapshot")
        s.close()
        return "interview, Talk, links, export, Word/CSV/JSON backup zip, snapshot"

    check("project workflow", workflow)

    def gui():
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance() or QApplication([sys.argv[0]])
        from .store import ProjectStore
        from .ui.context import AppContext
        from .ui.main_window import MainWindow
        ctx = AppContext()
        ctx.attach(ProjectStore(tmp / "Selftest" / "Selftest.pwdb"))
        win = MainWindow(ctx)
        win.show()
        app.processEvents()
        for i in range(win.nav.count()):
            win.nav.setCurrentRow(i)
            app.processEvents()
        win.close_project()
        win.hide()
        return f"{win.nav.count()} sections"

    check("main window (off-screen)", gui)

    ok = all(c["ok"] for c in checks if c["required"])
    report = {"version": APP_VERSION, "frozen": bool(getattr(sys, "frozen", False) or "__compiled__" in globals()),
              "ok": ok, "checks": checks}
    text = json.dumps(report, indent=2)
    if report_path:
        Path(report_path).write_text(text, encoding="utf-8")
    else:
        try:
            print(text)
        except Exception:
            pass
    return 0 if ok else 1
