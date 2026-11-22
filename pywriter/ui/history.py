"""History: every change ever made (revert any one), deleted entries, and
full snapshots (restore the whole project to a point in time)."""
from __future__ import annotations

import json
import os
import subprocess
import sys

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QComboBox, QDialog, QHBoxLayout, QHeaderView, QLabel, QListWidget,
                               QListWidgetItem, QMessageBox, QPushButton, QTableWidget, QTableWidgetItem,
                               QTabWidget, QVBoxLayout, QWidget)

from .common import center_on_screen


def open_folder(path) -> None:
    if sys.platform.startswith("win"):
        os.startfile(str(path))  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path)])


class HistoryDialog(QDialog):
    def __init__(self, ctx, entity_id: str | None = None, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.setWindowTitle("History & Backups")
        lay = QVBoxLayout(self)
        self.tabs = QTabWidget()
        lay.addWidget(self.tabs)

        # ---- changes
        ch = QWidget()
        cl = QVBoxLayout(ch)
        top = QHBoxLayout()
        top.addWidget(QLabel("Show changes for:"))
        self.filter = QComboBox()
        self.filter.addItem("All entries", "")
        for e in ctx.store.entities(include_deleted=True):
            self.filter.addItem(f"{e.label} ({e.id})", e.id)
        if entity_id:
            self.filter.setCurrentIndex(max(0, self.filter.findData(entity_id)))
        self.filter.currentIndexChanged.connect(self._load_changes)
        top.addWidget(self.filter, 1)
        cl.addLayout(top)
        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(["#", "When", "Entry", "Change", "Field", "Before → After", "Via"])
        self.table.horizontalHeader().setSectionResizeMode(5, QHeaderView.Stretch)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setWordWrap(True)
        cl.addWidget(self.table, 1)
        b = QHBoxLayout()
        rv = QPushButton("Revert selected change")
        rv.clicked.connect(self._revert)
        b.addWidget(rv)
        b.addStretch(1)
        cl.addLayout(b)
        self.tabs.addTab(ch, "Changes")

        # ---- deleted
        dw = QWidget()
        dl = QVBoxLayout(dw)
        self.deleted = QListWidget()
        dl.addWidget(self.deleted, 1)
        rb = QPushButton("Restore selected entry")
        rb.clicked.connect(self._undelete)
        dl.addWidget(rb)
        self.tabs.addTab(dw, "Deleted entries")

        # ---- snapshots
        sw = QWidget()
        sl = QVBoxLayout(sw)
        info = QLabel("Snapshots are complete copies of the project, made when you open or close it, after "
                      "interviews, and every few minutes while you work. Restoring one first makes a fresh "
                      "snapshot of the current state, so you can always go back.")
        info.setWordWrap(True)
        info.setObjectName("muted")
        sl.addWidget(info)
        self.snaps = QListWidget()
        sl.addWidget(self.snaps, 1)
        sb = QHBoxLayout()
        now = QPushButton("Back up now")
        now.clicked.connect(self._backup_now)
        sb.addWidget(now)
        rs = QPushButton("Restore selected snapshot")
        rs.clicked.connect(self._restore)
        sb.addWidget(rs)
        of = QPushButton("Open backups folder")
        of.clicked.connect(lambda: open_folder(ctx.backups.folder))
        sb.addWidget(of)
        sb.addStretch(1)
        sl.addLayout(sb)
        self.tabs.addTab(sw, "Snapshots")

        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        lay.addWidget(close, alignment=Qt.AlignRight)
        self._load_changes()
        self._load_deleted()
        self._load_snaps()
        center_on_screen(self, 0.6, 0.6)

    def _load_changes(self) -> None:
        store = self.ctx.store
        eid = self.filter.currentData()
        rows = store.revisions(eid or None, limit=1000)
        names = {e.id: e.label for e in store.entities(include_deleted=True)}
        self.table.setRowCount(len(rows))
        for i, r in enumerate(rows):
            old, new = r["old"] or "", r["new"] or ""
            if r["action"] in ("link", "unlink"):
                try:
                    d = json.loads(new or old)
                    desc = f"{names.get(d['src'], d['src'])} —{d['relation']}→ {names.get(d['dst'], d['dst'])}"
                except (ValueError, KeyError):
                    desc = new or old
            else:
                clip = lambda s: (s[:120] + "…") if len(s) > 120 else s  # noqa: E731
                desc = f"{clip(old)}  →  {clip(new)}" if old else clip(new)
            vals = [str(r["id"]), r["ts"].replace("T", " "), names.get(r["entity_id"], r["entity_id"] or "project"),
                    r["action"], r["key"] or "", desc, r["source"]]
            for c, v in enumerate(vals):
                it = QTableWidgetItem(v)
                if c == 0:
                    it.setData(Qt.UserRole, r["id"])
                self.table.setItem(i, c, it)
        self.table.resizeColumnsToContents()
        self.table.horizontalHeader().setSectionResizeMode(5, QHeaderView.Stretch)

    def _load_deleted(self) -> None:
        self.deleted.clear()
        for e in self.ctx.store.entities(include_deleted=True):
            if e.deleted:
                it = QListWidgetItem(f"{e.label}  ({e.id}, deleted {e.updated.replace('T', ' ')})")
                it.setData(Qt.UserRole, e.id)
                self.deleted.addItem(it)

    def _load_snaps(self) -> None:
        self.snaps.clear()
        for s in self.ctx.backups.list():
            it = QListWidgetItem(s.label)
            it.setData(Qt.UserRole, s)
            self.snaps.addItem(it)

    def _revert(self) -> None:
        row = self.table.currentRow()
        if row < 0:
            return
        rid = self.table.item(row, 0).data(Qt.UserRole)
        if self.ctx.store.revert(rid):
            self._load_changes()
            self._load_deleted()
        else:
            QMessageBox.information(self, "Revert", "That kind of change can't be reverted individually. "
                                                    "Try restoring a snapshot instead.")

    def _undelete(self) -> None:
        it = self.deleted.currentItem()
        if it:
            self.ctx.store.undelete_entity(it.data(Qt.UserRole))
            self._load_deleted()
            self._load_changes()

    def _backup_now(self) -> None:
        p = self.ctx.backups.snapshot("manual", force=True)
        self._load_snaps()
        self.ctx.bus.status.emit(f"Backed up to {p.name}" if p else "Nothing changed since the last backup.")

    def _restore(self) -> None:
        it = self.snaps.currentItem()
        if not it:
            return
        snap = it.data(Qt.UserRole)
        if QMessageBox.question(self, "Restore snapshot",
                                f"Restore the project to:\n{snap.label}\n\nThe current state will be "
                                f"snapshotted first, so this can be undone.") != QMessageBox.Yes:
            return
        safety = self.ctx.backups.restore(snap)
        QMessageBox.information(self, "Restored", f"Project restored.\nPrevious state saved as:\n"
                                                  f"{safety.name if safety else '(none)'}")
        self._load_snaps()
        self._load_changes()
        self._load_deleted()
