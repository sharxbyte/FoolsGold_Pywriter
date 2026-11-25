"""Shared application state passed to every window: the open project, question
library, voice engines, settings and a change-notification bus."""
from __future__ import annotations

import os

import datetime as _dt
from pathlib import Path

from PySide6.QtCore import QObject, QSettings, Signal

from .. import APP_NAME
from .. import audio
from ..backup import BackupManager
from ..library import Library
from ..llm import LocalAssistant
from ..store import ProjectStore
from ..voice import Listener, Speaker


class Bus(QObject):
    entity_changed = Signal(str)   # entity id
    links_changed = Signal(str)
    reloaded = Signal()            # whole project replaced (open / restore)
    meta_changed = Signal()
    open_entity = Signal(str)
    start_interview = Signal(str, str)  # kind, entity id ('' for new)
    status = Signal(str)


class VoiceTranscript:
    """Append-only ``<Title>_voice-transcript.txt`` in the project folder: everything
    heard, spoken, typed in Talk mode and answered in interviews, with timestamps.
    Lines are only ever appended, never rewritten, so it's a permanent record."""

    def __init__(self):
        self.path: Path | None = None

    def attach(self, store: ProjectStore | None) -> None:
        self.path = store.folder / f"{store.title}_voice-transcript.txt" if store else None
        if self.path and not self.path.exists():
            self.path.write_text(f"Voice transcript for {store.title}\n"
                                 f"(append-only record of everything said, heard and typed in PyWriter)\n\n",
                                 encoding="utf-8")
        self.write("Session", "Project opened")

    def write(self, who: str, text: str) -> None:
        text = (text or "").strip()
        if not self.path or not text:
            return
        ts = _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        text = text.replace("\r", "").replace("\n", "\n" + " " * 22)
        try:
            with self.path.open("a", encoding="utf-8") as f:
                f.write(f"[{ts}] {who}: {text}\n")
        except OSError:
            pass


class AppContext:
    def __init__(self):
        # PYWRITER_SETTINGS=<file.ini> keeps settings in a file instead (testing, portable installs)
        ini = os.environ.get("PYWRITER_SETTINGS")
        self.settings = QSettings(ini, QSettings.IniFormat) if ini else QSettings(APP_NAME, APP_NAME)
        self.library = Library()
        self.bus = Bus()
        self.speaker = Speaker()
        self.listener = Listener()
        self.assistant = LocalAssistant()
        self.transcript = VoiceTranscript()
        self.store: ProjectStore | None = None
        self.backups: BackupManager | None = None
        self.listener.final.connect(lambda t: self.transcript.write("Heard", t))
        self.speaker.spoke.connect(lambda t: self.transcript.write("PyWriter said", t))
        self.listener.record_path_fn = self._recording_path
        self.apply_voice_settings()

    # -------------------------------------------------- settings helpers
    def get(self, key: str, default=None, type_=None):
        v = self.settings.value(key, default)
        if type_ is bool:
            return v in (True, "true", "1", 1)
        if type_ is float:
            try:
                return float(v)
            except (TypeError, ValueError):
                return default
        if type_ is int:
            try:
                return int(v)
            except (TypeError, ValueError):
                return default
        return v

    def set(self, key: str, value) -> None:
        self.settings.setValue(key, value)

    def device_setting(self, kind: str) -> str:
        """'' = Windows communication device (default), 'system', or a device name."""
        v = self.get(f"voice/{kind}_device", "")
        return v if isinstance(v, str) else ""

    def apply_voice_settings(self) -> None:
        out_dev = audio.resolve_device(self.device_setting("output"), "output")
        engine = self.get("voice/engine", "") or ""
        if not engine:
            # Modern Windows voices can only play on the system default speaker. If the
            # communication speaker is a different device, default to an engine we can route.
            if self.device_setting("output") != audio.SYSTEM and audio.comm_differs_from_default("output"):
                from ..voice import piper_installed
                engine = "piper" if piper_installed() else "sapi"
        self.speaker.apply_settings(self.get("voice/rate", 0.0, float), self.get("voice/volume", 1.0, float),
                                    self.get("voice/name", "") or "", engine=engine,
                                    pitch=self.get("voice/pitch", 0.0, float),
                                    output_device=None if self.device_setting("output") == audio.SYSTEM
                                    else out_dev)
        from .. import voice as voice_mod
        voice_mod.PREFERRED_MODEL = self.get("voice/stt_model", "") or ""
        self.listener.device = audio.resolve_device(self.device_setting("input"), "input")
        self.listener.processing = {
            "noise_reduction": self.get("audio/noise_reduction", False, bool),
            "gate": self.get("audio/gate", False, bool),
            "compressor": self.get("audio/compressor", True, bool),
        }
        self.listener.record_fmt = self.get("audio/record_format", "") or ""
        self.assistant.configure(self.get("ai/enabled", False, bool), self.get("ai/model", "") or "")
        if self.assistant.usable:
            self.assistant.warm_up()

    def _recording_path(self, fmt: str):
        if not self.store:
            return None
        return audio.recording_path(self.store.folder, self.store.title, fmt)

    # -------------------------------------------------- project
    def attach(self, store: ProjectStore) -> None:
        self.store = store
        self.backups = BackupManager(store, keep_all=self.get("backup/keep_all", True, bool),
                                     max_snapshots=self.get("backup/max", 200, int))
        store.subscribe(self._on_store_event)
        self.transcript.attach(store)
        self.set("last_project", str(store.path))
        recent = [p for p in (self.get("recent", []) or []) if p != str(store.path)]
        if isinstance(recent, str):
            recent = [recent]
        self.set("recent", [str(store.path)] + recent[:9])
        self.bus.reloaded.emit()

    def _on_store_event(self, what: str, entity_id: str | None) -> None:
        if what == "entity" and entity_id:
            self.bus.entity_changed.emit(entity_id)
        elif what == "link" and entity_id:
            self.bus.links_changed.emit(entity_id)
        elif what == "reload":
            self.bus.reloaded.emit()
        elif what == "meta":
            self.bus.meta_changed.emit()

    def recent_projects(self) -> list[str]:
        r = self.get("recent", []) or []
        return [r] if isinstance(r, str) else list(r)
