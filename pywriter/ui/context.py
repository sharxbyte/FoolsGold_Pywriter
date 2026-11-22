"""Shared application state passed to every window: the open project, question
library, voice engines, settings and a change-notification bus."""
from __future__ import annotations

from PySide6.QtCore import QObject, QSettings, Signal

from ..backup import BackupManager
from ..library import Library
from ..store import ProjectStore
from ..voice import Listener, Speaker
from .. import APP_NAME


class Bus(QObject):
    entity_changed = Signal(str)   # entity id
    links_changed = Signal(str)
    reloaded = Signal()            # whole project replaced (open / restore)
    meta_changed = Signal()
    open_entity = Signal(str)
    start_interview = Signal(str, str)  # kind, entity id ('' for new)
    status = Signal(str)


class AppContext:
    def __init__(self):
        self.settings = QSettings(APP_NAME, APP_NAME)
        self.library = Library()
        self.bus = Bus()
        self.speaker = Speaker()
        self.listener = Listener()
        self.store: ProjectStore | None = None
        self.backups: BackupManager | None = None
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

    def apply_voice_settings(self) -> None:
        self.speaker.apply_settings(self.get("voice/rate", 0.0, float), self.get("voice/volume", 1.0, float),
                                    self.get("voice/name", "") or "", engine=self.get("voice/engine", "") or "",
                                    pitch=self.get("voice/pitch", 0.0, float))
        from .. import voice as voice_mod
        voice_mod.PREFERRED_MODEL = self.get("voice/stt_model", "") or ""
        dev = self.get("voice/input_device", None, int)
        self.listener.device = dev if dev is not None and dev >= 0 else None

    # -------------------------------------------------- project
    def attach(self, store: ProjectStore) -> None:
        self.store = store
        self.backups = BackupManager(store, keep_all=self.get("backup/keep_all", True, bool),
                                     max_snapshots=self.get("backup/max", 200, int))
        store.subscribe(self._on_store_event)
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
