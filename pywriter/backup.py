"""Rolling snapshot backups.

Each snapshot is a complete, standalone copy of the project database made with
SQLite's online backup API (safe even while the project is open). Snapshots are
written once and never modified. Restoring a snapshot first snapshots the current
state, so a restore can always be undone.
"""
from __future__ import annotations

import datetime as _dt
import shutil
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from .store import ProjectStore


@dataclass
class Snapshot:
    path: Path
    when: _dt.datetime
    reason: str
    revision: int

    @property
    def label(self) -> str:
        return f"{self.when:%Y-%m-%d %H:%M:%S}  ·  {self.reason}  ·  change #{self.revision}"


class BackupManager:
    def __init__(self, store: ProjectStore, keep_all: bool = True, max_snapshots: int = 200):
        self.store = store
        self.keep_all = keep_all
        self.max_snapshots = max_snapshots
        self._last_rev = self._latest_snapshot_revision()

    @property
    def folder(self) -> Path:
        d = self.store.folder / "backups"
        d.mkdir(exist_ok=True)
        return d

    def _latest_snapshot_revision(self) -> int:
        snaps = self.list()
        return snaps[0].revision if snaps else -1

    @property
    def dirty(self) -> bool:
        return self.store.revision_count() != self._last_rev

    def snapshot(self, reason: str = "manual", force: bool = False) -> Path | None:
        """Write a snapshot if anything changed since the last one (or if forced)."""
        rev = self.store.revision_count()
        if not force and rev == self._last_rev:
            return None
        ts = _dt.datetime.now().strftime("%Y-%m-%d_%H%M%S")
        safe_reason = "".join(c for c in reason if c.isalnum() or c in "-_")[:24] or "snap"
        name = f"{self.store.path.stem}__{ts}__r{rev:06d}__{safe_reason}{ProjectStore.EXT}"
        target = self.folder / name
        n = 1
        while target.exists():
            target = self.folder / name.replace(ProjectStore.EXT, f"_{n}{ProjectStore.EXT}")
            n += 1
        dst = sqlite3.connect(str(target))
        try:
            self.store.conn.backup(dst)
        finally:
            dst.close()
        self._last_rev = rev
        self.prune()
        return target

    def list(self) -> list[Snapshot]:
        out = []
        for p in self.folder.glob(f"*{ProjectStore.EXT}"):
            parts = p.stem.split("__")
            try:
                when = _dt.datetime.strptime(parts[1], "%Y-%m-%d_%H%M%S")
                rev = int(parts[2].lstrip("r"))
                reason = parts[3] if len(parts) > 3 else ""
            except (IndexError, ValueError):
                when = _dt.datetime.fromtimestamp(p.stat().st_mtime)
                rev, reason = 0, "unknown"
            out.append(Snapshot(p, when, reason, rev))
        out.sort(key=lambda s: (s.when, s.revision), reverse=True)
        return out

    def prune(self) -> None:
        if self.keep_all:
            return
        snaps = self.list()
        for s in snaps[self.max_snapshots:]:
            try:
                s.path.unlink()
            except OSError:
                pass

    def restore(self, snapshot: Snapshot) -> Path | None:
        """Replace the live project with a snapshot. Returns the safety snapshot path."""
        safety = self.snapshot("before-restore", force=True)
        self.store.close()
        shutil.copy2(snapshot.path, self.store.path)
        self.store.reopen()
        # note the restore in the (restored) change log
        self.store._log(None, "restore", snapshot.path.name, None, str(safety), "restore")
        self._last_rev = self.store.revision_count()
        return safety
