"""Manuscript: chapters/scenes with a plain editor, dictation and read-aloud.
Scene text is stored in the project database (field 'text'), autosaved as you type."""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QAbstractItemView, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QListWidget,
                               QListWidgetItem, QMessageBox, QPlainTextEdit, QPushButton, QSplitter,
                               QVBoxLayout, QWidget)

from ..voice import parse_command
from .common import DictationTarget, EntityBrowser, LevelMeter, linkify


class SceneList(QListWidget):
    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.setDragDropMode(QAbstractItemView.InternalMove)

    def dropEvent(self, e):
        super().dropEvent(e)
        with self.ctx.store.batch():
            for i in range(self.count()):
                self.ctx.store.move(self.item(i).data(Qt.UserRole), float(i + 1))


class ManuscriptPanel(QWidget):
    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.current: str | None = None
        self._dictating = False
        lay = QVBoxLayout(self)
        h = QLabel("Manuscript")
        h.setObjectName("h1")
        lay.addWidget(h)
        split = QSplitter(Qt.Horizontal)
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        self.scenes = SceneList(ctx)
        self.scenes.currentItemChanged.connect(self._select)
        ll.addWidget(self.scenes, 1)
        bl = QHBoxLayout()
        add = QPushButton("+ Scene")
        add.clicked.connect(self._add)
        bl.addWidget(add)
        rn = QPushButton("Rename")
        rn.clicked.connect(self._rename)
        bl.addWidget(rn)
        dl = QPushButton("Delete")
        dl.clicked.connect(self._delete)
        bl.addWidget(dl)
        ll.addLayout(bl)
        split.addWidget(left)

        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        self.synopsis = QLineEdit()
        self.synopsis.setPlaceholderText("One-line synopsis of this scene")
        self.synopsis.editingFinished.connect(lambda: self.current and
                                              ctx.store.set_field(self.current, "synopsis", self.synopsis.text()))
        rl.addWidget(self.synopsis)
        self.editor = QPlainTextEdit()
        self.editor.setPlaceholderText("Write here, or press Dictate and talk…")
        f = self.editor.font()
        f.setPointSizeF(f.pointSizeF() * 1.15)
        self.editor.setFont(f)
        self.editor.textChanged.connect(self._changed)
        rl.addWidget(self.editor, 3)
        self.mentions = EntityBrowser(ctx)
        self.mentions.setMaximumHeight(90)
        self.mentions.entity_clicked.connect(ctx.bus.open_entity.emit)
        rl.addWidget(self.mentions)
        tb = QHBoxLayout()
        self.dictate = QPushButton("🎤 Dictate")
        self.dictate.setCheckable(True)
        self.dictate.toggled.connect(self._toggle_dictate)
        tb.addWidget(self.dictate)
        self.meter = LevelMeter()
        tb.addWidget(self.meter)
        rd = QPushButton("🔊 Read selection / scene")
        rd.clicked.connect(self._read)
        tb.addWidget(rd)
        st = QPushButton("■ Stop")
        st.clicked.connect(ctx.speaker.stop)
        tb.addWidget(st)
        tb.addStretch(1)
        self.count = QLabel()
        self.count.setObjectName("muted")
        tb.addWidget(self.count)
        rl.addLayout(tb)
        split.addWidget(right)
        split.setStretchFactor(1, 4)
        lay.addWidget(split, 1)

        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(1200)
        self._save_timer.timeout.connect(self.save)
        ctx.bus.reloaded.connect(self.refresh)
        ctx.listener.final.connect(self._on_final)
        ctx.listener.level.connect(lambda v: self._dictating and self.meter.set_level(v))

    def refresh(self) -> None:
        if not self.ctx.store:
            return
        self.save()
        self.scenes.blockSignals(True)
        self.scenes.clear()
        for s in sorted(self.ctx.store.entities("scene"), key=lambda e: e.sort_order):
            it = QListWidgetItem(s.label)
            it.setData(Qt.UserRole, s.id)
            self.scenes.addItem(it)
        self.scenes.blockSignals(False)
        if self.scenes.count():
            idx = 0
            for i in range(self.scenes.count()):
                if self.scenes.item(i).data(Qt.UserRole) == self.current:
                    idx = i
            self.scenes.setCurrentRow(idx)
            self._select(self.scenes.currentItem(), None)
        else:
            self.current = None
            self.editor.blockSignals(True)
            self.editor.clear()
            self.editor.blockSignals(False)
            self.editor.setEnabled(False)

    def _select(self, item, _prev) -> None:
        self.save()
        if not item:
            return
        self.current = item.data(Qt.UserRole)
        e = self.ctx.store.get(self.current)
        self.editor.setEnabled(True)
        self.editor.blockSignals(True)
        self.editor.setPlainText(e.fields.get("text", ""))
        self.editor.blockSignals(False)
        self.synopsis.setText(e.fields.get("synopsis", ""))
        self._update_info()

    def _changed(self) -> None:
        self._save_timer.start()
        self._update_info()

    def _update_info(self) -> None:
        text = self.editor.toPlainText()
        self.count.setText(f"{len(text.split())} words")

    def save(self) -> None:
        if self.current and self.ctx.store and self.ctx.store.get(self.current):
            self.ctx.store.set_field(self.current, "text", self.editor.toPlainText(), source="manuscript")
            # show linked mentions of story-bible entries under the editor
            names = sorted({n for eid, _, n in self.ctx.store.all_names()
                            if len(n) >= 3 and n.lower() in self.editor.toPlainText().lower()})
            self.mentions.setHtml("<span style='color:gray'>In this scene: </span>" +
                                  linkify(self.ctx.store, " · ".join(names)) if names else "")

    def _add(self) -> None:
        n = self.scenes.count() + 1
        name, ok = QInputDialog.getText(self, "New scene", "Scene or chapter title:", text=f"Scene {n}")
        if ok and name.strip():
            eid = self.ctx.store.create_entity("scene", name.strip())
            self.current = eid
            self.refresh()

    def _rename(self) -> None:
        if not self.current:
            return
        e = self.ctx.store.get(self.current)
        name, ok = QInputDialog.getText(self, "Rename", "Title:", text=e.name)
        if ok and name.strip():
            self.ctx.store.set_field(self.current, "name", name.strip())
            self.refresh()

    def _delete(self) -> None:
        if self.current and QMessageBox.question(self, "Delete scene", "Delete this scene? "
                                                 "You can restore it from History.") == QMessageBox.Yes:
            self.save()
            self.ctx.store.delete_entity(self.current)
            self.current = None
            self.refresh()

    def _read(self) -> None:
        sel = self.editor.textCursor().selectedText().replace(" ", "\n")
        self.ctx.speaker.say(sel or self.editor.toPlainText())

    def _toggle_dictate(self, on: bool) -> None:
        if on:
            if not self.ctx.listener.available:
                from ..voice import stt_status
                QMessageBox.information(self, "Speech recognition", stt_status())
                self.dictate.setChecked(False)
                return
            self._dictating = True
            self.ctx.listener.start()
        else:
            self._dictating = False
            self.ctx.listener.stop()

    def _on_final(self, text: str) -> None:
        if not self._dictating or not self.editor.isEnabled():
            return
        cmd, rest = parse_command(text)
        if cmd == "pause":
            self.dictate.setChecked(False)
            return
        if cmd == "scratch":
            self.editor.undo()
            return
        DictationTarget(self.editor).insert(text)
