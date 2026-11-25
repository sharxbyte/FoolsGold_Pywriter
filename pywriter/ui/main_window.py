"""Main window."""
from __future__ import annotations

import platform
import sys

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (QApplication, QDialog, QDockWidget, QHBoxLayout, QLabel, QListWidget,
                               QListWidgetItem, QMainWindow, QMenu, QMessageBox, QPushButton, QSplitter,
                               QStackedWidget, QTabWidget, QToolBar, QToolButton, QVBoxLayout, QWidget)

from .. import APP_DISPLAY_NAME, APP_VERSION
from ..export import export_manuscript, export_story_bible
from ..store import KINDS, ProjectStore
from ..voice import is_no, is_yes, stt_status
from .common import center_on_screen
from .entity_page import EntityPage
from .history import HistoryDialog, open_folder
from .interview import InterviewDialog
from .lists import EntityListPanel, OverviewPanel
from .manuscript import ManuscriptPanel
from .map_view import MapView
from .project_dialog import ProjectDialog
from .settings_dialog import SettingsDialog, download_model
from .talk import TalkPanel
from .theme import apply_theme

SECTIONS = {
    "Fiction": ["overview", "character", "location", "group", "item", "plot", "event", "theme", "source",
                "map", "scene"],
    "Biography": ["overview", "character", "event", "location", "group", "theme", "source", "map", "scene"],
    "Non-Fiction": ["overview", "topic", "source", "character", "event", "location", "group", "theme",
                    "map", "scene"],
}
SECTION_LABELS = {"overview": "Overview", "map": "Map", "scene": "Manuscript"}


class VoicePrompt(QDialog):
    """Yes/no question that is read aloud and can be answered by voice when
    narration is the default."""

    def __init__(self, ctx, text: str, parent=None, yes="Yes", no="No"):
        super().__init__(parent)
        self.ctx = ctx
        self.setWindowTitle(APP_DISPLAY_NAME)
        lay = QVBoxLayout(self)
        lab = QLabel(text)
        lab.setObjectName("question")
        lab.setWordWrap(True)
        lay.addWidget(lab)
        self.hint = QLabel()
        self.hint.setObjectName("muted")
        lay.addWidget(self.hint)
        row = QHBoxLayout()
        row.addStretch(1)
        n = QPushButton(no)
        n.clicked.connect(self.reject)
        y = QPushButton(yes)
        y.setObjectName("primary")
        y.setDefault(True)
        y.clicked.connect(self.accept)
        row.addWidget(n)
        row.addWidget(y)
        lay.addLayout(row)
        self.resize(560, 200)
        self.voice = ctx.get("voice/narration_default", False, bool) and ctx.speaker.available
        if self.voice:
            ctx.speaker.finished.connect(self._listen)
            ctx.listener.final.connect(self._heard)
            QTimer.singleShot(200, lambda: ctx.speaker.say(text))

    def _listen(self):
        if self.ctx.listener.available:
            self.hint.setText("Listening for yes or no…")
            self.ctx.listener.start()

    def _heard(self, text: str):
        if is_yes(text):
            self.accept()
        elif is_no(text):
            self.reject()

    def done(self, r):
        if self.voice:
            for sig, slot in ((self.ctx.speaker.finished, self._listen), (self.ctx.listener.final, self._heard)):
                try:
                    sig.disconnect(slot)
                except (RuntimeError, TypeError):
                    pass
            self.ctx.listener.stop()
        super().done(r)


class MainWindow(QMainWindow):
    def __init__(self, ctx):
        super().__init__()
        self.ctx = ctx
        self.pages: dict[str, EntityPage] = {}
        self._in_interview = False
        self._distraction = False
        self.setWindowTitle(APP_DISPLAY_NAME)
        self._export_timer = QTimer(self)
        self._export_timer.setSingleShot(True)
        self._export_timer.setInterval(2500)
        self._export_timer.timeout.connect(self.export_bible)

        # ---- left nav + browse stack
        self.nav = QListWidget()
        self.nav.setObjectName("nav")
        self.nav.setMinimumWidth(170)
        self.nav.setMaximumWidth(240)
        self.nav.currentRowChanged.connect(self._nav_changed)
        self.stack = QStackedWidget()
        self.tabs = QTabWidget()
        self.tabs.setTabsClosable(True)
        self.tabs.setMovable(True)
        self.tabs.tabCloseRequested.connect(self._close_tab)
        self.tabs.currentChanged.connect(self._tab_changed)
        self.tabs.addTab(self.stack, "Browse")
        self.tabs.tabBar().setTabButton(0, self.tabs.tabBar().ButtonPosition.RightSide, None)
        split = QSplitter(Qt.Horizontal)
        split.addWidget(self.nav)
        split.addWidget(self.tabs)
        split.setStretchFactor(1, 1)
        split.setCollapsible(0, False)
        split.setSizes([190, 1000])
        self.setCentralWidget(split)

        # ---- talk dock
        self.talk = TalkPanel(ctx)
        self.talk_dock = QDockWidget("Talk", self)
        self.talk_dock.setObjectName("talk_dock")
        self.talk_dock.setWidget(self.talk)
        self.addDockWidget(Qt.RightDockWidgetArea, self.talk_dock)
        self.talk_dock.setVisible(ctx.get("ui/talk_visible", True, bool))

        self._build_actions()
        self.status = QLabel()
        self.statusBar().addPermanentWidget(self.status)

        ctx.bus.open_entity.connect(self.open_entity)
        ctx.bus.start_interview.connect(self._start_interview_signal)
        ctx.bus.status.connect(lambda m: self.statusBar().showMessage(m, 6000))
        ctx.bus.entity_changed.connect(self._entity_changed)
        ctx.bus.meta_changed.connect(self._update_title)

        self._backup_timer = QTimer(self)
        self._backup_timer.timeout.connect(lambda: self.snapshot("auto"))
        self._backup_timer.start(max(1, ctx.get("backup/interval_min", 5, int)) * 60_000)

        center_on_screen(self, 0.5, 0.5)
        self.load_project_ui()

    # ================================================================ actions
    def _build_actions(self) -> None:
        mb = self.menuBar()
        fm = mb.addMenu("&File")
        fm.addAction("New / Open project…", self.switch_project, QKeySequence("Ctrl+O"))
        em = fm.addMenu("Export")
        em.addAction("Complete backup (.zip)…", lambda: self._export_as("backup"))
        em.addSeparator()
        em.addAction("Story Bible as Word (.docx)…", lambda: self._export_as("bible_docx"))
        em.addAction("Manuscript as Word (.docx)…", lambda: self._export_as("manuscript_docx"))
        em.addAction("Spreadsheets (.csv)…", lambda: self._export_as("csv"))
        em.addAction("Whole project as JSON…", lambda: self._export_as("json"))
        em.addSeparator()
        em.addAction("Story Bible as Markdown (project folder)", lambda: self._export(True))
        em.addAction("Manuscript as Markdown (project folder)", lambda: self._export(False))
        fm.addAction("Open project folder", lambda: open_folder(self.ctx.store.folder))
        fm.addAction("Import from PyWriter v10/v11 (.json)…", self.import_old)
        fm.addSeparator()
        fm.addAction("Exit", self.close, QKeySequence("Ctrl+Q"))

        self.interview_menu = mb.addMenu("&Interview")

        vm = mb.addMenu("&Voice")
        vm.addAction("Download speech model…", lambda: download_model(self, self.ctx))
        vm.addAction("Voice commands…", self._voice_help)
        vm.addAction("Stop reading", self.ctx.speaker.stop, QKeySequence("Esc"))

        view = mb.addMenu("&View")
        self.talk_action = self.talk_dock.toggleViewAction()
        self.talk_action.setShortcut(QKeySequence("Ctrl+T"))
        view.addAction(self.talk_action)
        self.df_action = QAction("Distraction-free mode", self, checkable=True)
        self.df_action.setShortcut(QKeySequence("F11"))
        self.df_action.toggled.connect(self.toggle_distraction)
        view.addAction(self.df_action)
        tm = view.addMenu("Theme")
        from .theme import THEMES
        for name in THEMES:
            tm.addAction(name.title(), lambda n=name: self._set_theme(n))
        view.addAction("Larger text", lambda: self._scale(0.1), QKeySequence("Ctrl+="))
        view.addAction("Smaller text", lambda: self._scale(-0.1), QKeySequence("Ctrl+-"))

        tools = mb.addMenu("&Tools")
        tools.addAction("History && backups…", self.show_history, QKeySequence("Ctrl+H"))
        tools.addAction("Back up now", lambda: self.snapshot("manual", force=True, announce=True))
        tools.addAction("Undo last change", self._undo, QKeySequence("Ctrl+Shift+Z"))
        tools.addAction("Settings…", self.show_settings, QKeySequence("Ctrl+,"))
        tools.addAction("Local AI assistant…", self.show_ai)
        tools.addAction("Diagnostics…", self.show_diagnostics)

        hm = mb.addMenu("&Help")
        hm.addAction("About", self._about)

        tb = QToolBar("Main")
        tb.setObjectName("main_toolbar")
        tb.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.addToolBar(tb)
        self.toolbar = tb
        g = QAction("🎙 Guided Interview", self)
        g.setToolTip("Walk through the whole project, step by step")
        g.triggered.connect(self.guided_interview)
        tb.addAction(g)
        self.new_btn = QToolButton()
        self.new_btn.setText("➕ New")
        self.new_btn.setPopupMode(QToolButton.InstantPopup)
        self.new_menu = QMenu(self)
        self.new_btn.setMenu(self.new_menu)
        tb.addWidget(self.new_btn)
        tb.addSeparator()
        tb.addAction(self.talk_action)
        tb.addAction("🗺 Map", lambda: self._goto_section("map"))
        tb.addAction("✍ Manuscript", lambda: self._goto_section("scene"))
        tb.addSeparator()
        tb.addAction("🕘 History", self.show_history)
        tb.addAction("💾 Back up", lambda: self.snapshot("manual", force=True, announce=True))
        tb.addAction(self.df_action)
        tb.addAction("⚙ Settings", self.show_settings)

    def _rebuild_interview_menus(self) -> None:
        self.interview_menu.clear()
        self.new_menu.clear()
        s = self.ctx.store
        self.interview_menu.addAction("Guided Story Interview", self.guided_interview, QKeySequence("Ctrl+G"))
        self.interview_menu.addSeparator()
        for pack in self.ctx.library.project_packs(s.project_type):
            self.interview_menu.addAction(pack.title, lambda pid=pack.id: self.run_interview(pid))
        self.interview_menu.addSeparator()
        for pack in self.ctx.library.packs_for(s.project_type):
            if pack.kind == "project":
                continue
            label = f"New {KINDS[pack.kind][1].lower()}…"
            self.interview_menu.addAction(pack.title, lambda pid=pack.id: self.run_interview(pid))
            self.new_menu.addAction(label, lambda pid=pack.id: self.run_interview(pid))
        self.new_menu.addAction("New scene…", lambda: (self._goto_section("scene"), self.manuscript._add()))

    # ================================================================ project
    def load_project_ui(self) -> None:
        s = self.ctx.store
        # close entity tabs
        while self.tabs.count() > 1:
            self.tabs.removeTab(1)
        self.pages.clear()
        while self.stack.count():
            w = self.stack.widget(0)
            self.stack.removeWidget(w)
            w.deleteLater()
        self.nav.blockSignals(True)
        self.nav.clear()
        self.sections: list[str] = []
        for sec in SECTIONS.get(s.project_type, SECTIONS["Fiction"]):
            if sec == "overview":
                w = OverviewPanel(self.ctx)
                w.guided.connect(self.guided_interview)
                self.overview = w
            elif sec == "map":
                w = MapView(self.ctx)
            elif sec == "scene":
                w = ManuscriptPanel(self.ctx)
                self.manuscript = w
            else:
                w = EntityListPanel(self.ctx, sec)
            label = SECTION_LABELS.get(sec) or KINDS[sec][2]
            if sec == "character" and s.project_type != "Fiction":
                label = "People"
            if sec == "location" and s.project_type != "Fiction":
                label = "Places"
            self.nav.addItem(QListWidgetItem(label))
            self.stack.addWidget(w)
            self.sections.append(sec)
            if hasattr(w, "refresh"):
                w.refresh()
        self.nav.blockSignals(False)
        self.nav.setCurrentRow(0)
        self._rebuild_interview_menus()
        self._update_title()
        self.talk.reset()
        # snapshot on open if anything changed since the last snapshot
        self.snapshot("open")
        self.export_bible()

    def _update_title(self) -> None:
        if self.ctx.store:
            self.setWindowTitle(f"{self.ctx.store.title} — {APP_DISPLAY_NAME}")
            self._update_status()

    def _update_status(self) -> None:
        s = self.ctx.store
        if not s:
            return
        snaps = self.ctx.backups.list()
        last = f"last backup {snaps[0].when:%H:%M}" if snaps else "no backups yet"
        self.status.setText(f"All changes saved · change #{s.revision_count()} · {last}")

    def switch_project(self) -> None:
        d = ProjectDialog(self.ctx, self)
        if d.exec() and d.result_store:
            self.close_project()
            self.ctx.attach(d.result_store)
            self.load_project_ui()
            if d.result_store.revision_count() <= 4:
                self._offer_guided()

    def close_project(self) -> None:
        if not self.ctx.store:
            return
        for p in self.pages.values():
            p.save_pending()
            p._save_timer.stop()
            p._refresh_timer.stop()
        if hasattr(self, "manuscript"):
            self.manuscript.save()
            self.manuscript._save_timer.stop()
        self._export_timer.stop()
        self.export_bible()
        self.snapshot("close")
        self.ctx.transcript.write("Session", "Project closed")
        store, self.ctx.store = self.ctx.store, None   # nothing may touch the closed database
        store.close()

    def _offer_guided(self) -> None:
        if VoicePrompt(self.ctx, "Your project is ready. Would you like to start the Guided Story Interview "
                                 "now? It walks you through everything one question at a time.", self,
                       yes="Start interview", no="Not now").exec():
            self.guided_interview()

    # ================================================================ saving
    def snapshot(self, reason: str, force: bool = False, announce: bool = False) -> None:
        if not self.ctx.backups:
            return
        try:
            p = self.ctx.backups.snapshot(reason, force=force)
        except Exception as e:
            self.statusBar().showMessage(f"Backup failed: {e}", 8000)
            return
        if announce:
            self.statusBar().showMessage(f"Backed up: {p.name}" if p else "Nothing new to back up.", 6000)
        self._update_status()

    def export_bible(self) -> None:
        if not self.ctx.store:
            return
        try:
            export_story_bible(self.ctx.store, self.ctx.library)
            if self.ctx.store.entities("scene"):
                export_manuscript(self.ctx.store)
        except Exception as e:
            self.statusBar().showMessage(f"Couldn't write the Story Bible file: {e}", 8000)

    def _export(self, bible: bool) -> None:
        p = export_story_bible(self.ctx.store, self.ctx.library) if bible else export_manuscript(self.ctx.store)
        self.statusBar().showMessage(f"Exported {p}", 8000)
        open_folder(p.parent)

    def _export_as(self, what: str) -> None:
        """Export to a place the writer chooses, e.g. for backups kept outside PyWriter."""
        import datetime as _dt
        from pathlib import Path
        from PySide6.QtWidgets import QFileDialog
        from .. import exporters as ex
        s = self.ctx.store
        if what == "manuscript_docx" and not s.entities("scene"):
            QMessageBox.information(self, "Export", "There are no manuscript scenes to export yet.")
            return
        self._save_on_switch()
        start_dir = Path(self.ctx.get("export/last_dir", "") or (Path.home() / "Documents"))
        title = ex.safe_filename(s.title)
        stamp = f"{_dt.datetime.now():%Y-%m-%d %H%M}"
        if what == "csv":
            folder = QFileDialog.getExistingDirectory(self, "Choose where to put the spreadsheets", str(start_dir))
            if not folder:
                return
            target = Path(folder) / f"{title} - spreadsheets {stamp}"
        else:
            name, filt = {
                "backup": (f"{title} - PyWriter backup {stamp}.zip", "Zip archive (*.zip)"),
                "bible_docx": (f"{title} - Story Bible.docx", "Word document (*.docx)"),
                "manuscript_docx": (f"{title} - Manuscript.docx", "Word document (*.docx)"),
                "json": (f"{title} - project {stamp}.json", "JSON (*.json)"),
            }[what]
            f, _ = QFileDialog.getSaveFileName(self, "Export", str(start_dir / name), filt)
            if not f:
                return
            target = Path(f)
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            if what == "backup":
                out = ex.export_backup_zip(s, self.ctx.library, target)
            elif what == "bible_docx":
                out = ex.export_story_bible_docx(s, self.ctx.library, target)
            elif what == "manuscript_docx":
                out = ex.export_manuscript_docx(s, target)
            elif what == "json":
                out = ex.export_json(s, target)
            else:
                ex.export_csv(s, self.ctx.library, target)
                out = target
        except Exception as e:
            QApplication.restoreOverrideCursor()
            QMessageBox.warning(self, "Export failed", f"Couldn't export:\n\n{e}")
            return
        QApplication.restoreOverrideCursor()
        self.ctx.set("export/last_dir", str(target.parent))
        self.statusBar().showMessage(f"Exported {out}", 10000)
        if QMessageBox.question(self, "Exported", f"Saved:\n{out}\n\nOpen the folder?") == QMessageBox.Yes:
            open_folder(out if out.is_dir() else out.parent)

    def _entity_changed(self, eid: str) -> None:
        self._export_timer.start()
        self._update_status()
        e = self.ctx.store.get(eid, with_fields=False)
        if e and eid in self.pages:
            i = self.tabs.indexOf(self.pages[eid])
            if i >= 0:
                if e.deleted:
                    self.tabs.removeTab(i)
                    self.pages.pop(eid).deleteLater()
                else:
                    self.tabs.setTabText(i, e.label)

    # ================================================================ navigation
    def _nav_changed(self, row: int) -> None:
        if 0 <= row < self.stack.count():
            self.stack.setCurrentIndex(row)
            self.tabs.setCurrentIndex(0)
            self._save_on_switch()

    def _goto_section(self, sec: str) -> None:
        if sec in self.sections:
            self.nav.setCurrentRow(self.sections.index(sec))
            self.tabs.setCurrentIndex(0)

    def _tab_changed(self, idx: int) -> None:
        self._save_on_switch()
        w = self.tabs.widget(idx)
        if isinstance(w, EntityPage):
            self.talk.set_focus_entity(w.entity_id)

    def _save_on_switch(self) -> None:
        """Save point when switching tabs or sections: flush edits and refresh exports."""
        for p in self.pages.values():
            p.save_pending()
        if hasattr(self, "manuscript"):
            self.manuscript.save()
        self._export_timer.start()

    def open_entity(self, eid: str) -> None:
        e = self.ctx.store.get(eid, with_fields=False)
        if not e:
            return
        if e.kind == "project":
            self._goto_section("overview")
            return
        if e.kind == "scene":
            self._goto_section("scene")
            return
        page = self.pages.get(eid)
        if page is None:
            page = EntityPage(self.ctx, eid)
            self.pages[eid] = page
            self.tabs.addTab(page, e.label)
        self.tabs.setCurrentWidget(page)
        self.talk.set_focus_entity(eid)

    def _close_tab(self, idx: int) -> None:
        w = self.tabs.widget(idx)
        if isinstance(w, EntityPage):
            w.save_pending()
            self.pages.pop(w.entity_id, None)
            self.tabs.removeTab(idx)
            w.deleteLater()

    # ================================================================ interviews
    def _start_interview_signal(self, pack_id: str, target: str) -> None:
        if target.startswith("parent:"):
            parent = self.ctx.store.get(target[7:], with_fields=False)
            self.run_interview(pack_id, preset={"parent": parent.name if parent else ""})
        else:
            self.run_interview(pack_id, target or None)

    def run_interview(self, pack_id: str, entity_id: str | None = None, preset: dict | None = None,
                      loop: bool = True) -> bool:
        """Run an interview (and 'add another?' repeats). Returns False if the writer
        stopped early."""
        if self._in_interview:
            return False
        pack = self.ctx.library.pack(pack_id)
        if not pack:
            return False
        self.talk.stop_listening()
        self._in_interview = True
        try:
            queue: list[tuple[str, str | None, dict | None]] = [(pack_id, entity_id, preset)]
            while queue:
                pid, eid, pre = queue.pop(0)
                p = self.ctx.library.pack(pid)
                dlg = InterviewDialog(self.ctx, p, eid, pre, self)
                accepted = dlg.exec()
                res = dlg.result_commit
                self.snapshot("interview")
                self.export_bible()
                if res and res.entity_id:
                    self.ctx.bus.entity_changed.emit(res.entity_id)
                if not accepted:
                    return False
                # sub-locations etc. requested by answers ("are there places inside X?")
                for kind_pack, spawn_preset in (res.spawns if res else []):
                    parent = spawn_preset.get("parent", "")
                    sub = self.ctx.library.pack_for_kind(kind_pack, self.ctx.store.project_type) or \
                        self.ctx.library.pack(kind_pack)
                    if sub and VoicePrompt(self.ctx, f"You said there are notable places inside {parent}. "
                                                     f"Would you like to describe one now?", self).exec():
                        queue.insert(0, (sub.id, None, spawn_preset))
                if loop and dlg.wants_another:
                    queue.append((pid, None, pre if pre and "parent" in pre else None))
            return True
        finally:
            self._in_interview = False

    def guided_interview(self) -> None:
        flow = self.ctx.library.flow(self.ctx.store.project_type)
        if not flow:
            QMessageBox.information(self, "Guided interview", "No guided flow is defined for this project type.")
            return
        for step in flow:
            pack = self.ctx.library.pack(step["pack"])
            if not pack:
                continue
            ask = step.get("ask")
            if pack.kind == "project":
                if self.ctx.store.project_entity().fields and step["pack"] in self._completed_project_packs():
                    if not VoicePrompt(self.ctx, f"You've already done the {pack.title} interview. "
                                                 f"Would you like to go through it again?", self).exec():
                        continue
            elif ask:
                existing = len(self.ctx.store.entities(pack.kind))
                text = ask if not existing else \
                    f"You have {existing} {KINDS[pack.kind][2].lower()} so far. Would you like to add more?"
                prompt = VoicePrompt(self.ctx, text, self, yes="Yes", no="Skip")
                if not prompt.exec():
                    continue
            if not self.run_interview(pack.id, loop=step.get("loop", False)):
                if not VoicePrompt(self.ctx, "Would you like to continue the guided interview with the next "
                                             "step?", self, yes="Continue", no="Stop here").exec():
                    return
        VoicePrompt(self.ctx, "That's the whole guided interview. Everything is saved — you can re-interview "
                              "any entry from its page, or keep adding details in Talk mode.", self,
                    yes="Done", no="Close").exec()

    def _completed_project_packs(self) -> set[str]:
        fields = self.ctx.store.project_entity().fields
        done = set()
        for p in self.ctx.library.project_packs(self.ctx.store.project_type):
            keys = [q.key for q in p.questions if q.key != "name"]
            if keys and sum(1 for k in keys if fields.get(k)) >= max(1, len(keys) // 3):
                done.add(p.id)
        return done

    # ================================================================ misc
    def import_old(self) -> None:
        from PySide6.QtWidgets import QFileDialog
        from ..importer import import_v11
        f, _ = QFileDialog.getOpenFileName(self, "Import a PyWriter v10/v11 project", "",
                                           "PyWriter v11 project (*.json)")
        if not f:
            return
        self.snapshot("before-import", force=True)
        try:
            c = import_v11(f, self.ctx.store, self.ctx.library)
        except Exception as e:
            QMessageBox.warning(self, "Import", f"Couldn't import that file:\n{e}")
            return
        QMessageBox.information(self, "Import", f"Imported {c['entries']} entries "
                                f"({c['matched']} answers matched to the new questions, {c['unmatched']} kept "
                                f"under 'Imported from v11'), {c['notes']} notes and {c['links']} links.\n\n"
                                f"A snapshot was taken first, so you can undo this from History.")


    def show_history(self) -> None:
        w = self.tabs.currentWidget()
        HistoryDialog(self.ctx, w.entity_id if isinstance(w, EntityPage) else None, self).exec()
        self._update_status()

    def show_ai(self, first_run: bool = False) -> None:
        from .ai_dialog import LocalAIDialog
        LocalAIDialog(self.ctx, self, first_run=first_run).exec()
        self.ctx.set("ai/offered", True)

    def first_run_offers(self, new_project: bool) -> None:
        """Offer the optional local AI once, then (for a new project) the guided interview."""
        if not self.ctx.get("ai/offered", False, bool):
            self.show_ai(first_run=True)
        if new_project:
            self._offer_guided()

    def show_settings(self) -> None:
        if SettingsDialog(self.ctx, self).exec():
            apply_theme(QApplication.instance(), self.ctx.get("ui/theme", "light"),
                        self.ctx.get("ui/font_scale", 1.0, float))
            self._backup_timer.start(max(1, self.ctx.get("backup/interval_min", 5, int)) * 60_000)

    def _set_theme(self, name: str) -> None:
        self.ctx.set("ui/theme", name)
        apply_theme(QApplication.instance(), name, self.ctx.get("ui/font_scale", 1.0, float))

    def _scale(self, delta: float) -> None:
        v = max(0.8, min(2.5, self.ctx.get("ui/font_scale", 1.0, float) + delta))
        self.ctx.set("ui/font_scale", v)
        apply_theme(QApplication.instance(), self.ctx.get("ui/theme", "light"), v)

    def _undo(self) -> None:
        row = self.ctx.store.undo_last()
        self.statusBar().showMessage("Undid the last change." if row else "Nothing to undo.", 5000)

    def toggle_distraction(self, on: bool) -> None:
        self._distraction = on
        self.nav.setVisible(not on)
        self.toolbar.setVisible(not on)
        self.menuBar().setVisible(not on)
        self.statusBar().setVisible(not on)
        if on:
            self._talk_was_visible = self.talk_dock.isVisible()
            self.talk_dock.hide()
            self.showFullScreen()
            self._goto_section("scene")
            self.statusBar().showMessage("Press F11 to leave distraction-free mode")
        else:
            self.showNormal()
            self.talk_dock.setVisible(getattr(self, "_talk_was_visible", True))

    def keyPressEvent(self, e):
        if self._distraction and e.key() in (Qt.Key_F11, Qt.Key_Escape):
            self.df_action.setChecked(False)
            return
        super().keyPressEvent(e)

    def _voice_help(self) -> None:
        QMessageBox.information(self, "Voice commands", (
            "During interviews (Narration mode, F5):\n"
            "  • “next question, confirm” — save and move on (also: finished / continue / proceed + confirm/yes)\n"
            "  • “go back” — previous question\n"
            "  • “repeat the question”\n"
            "  • “read my answer”\n"
            "  • “skip question”\n"
            "  • “scratch that” — remove the last thing you said\n"
            "  • “stop listening”\n"
            "  • “end interview”\n\n"
            "After 10 seconds of silence PyWriter asks whether you're finished; after another silence it pauses.\n\n"
            "While dictating: say “comma”, “full stop”, “question mark”, “new line”, “new paragraph”.\n\n"
            "In Talk mode, just describe your story, or say: open X · tell me about X · interview X · "
            "add a character named X · change X's age to 30 · delete X · undo."))

    def show_diagnostics(self) -> None:
        import PySide6
        lib = self.ctx.library
        lines = [f"{APP_DISPLAY_NAME} {APP_VERSION}", f"Python {sys.version.split()[0]} · Qt {PySide6.__version__}"
                 f" · {platform.platform()}", "",
                 f"Question packs: {len(lib.packs)} loaded from {lib.folder}"]
        lines += [f"  ⚠ {e}" for e in lib.errors]
        lines += ["", f"Text-to-speech: {'available' if self.ctx.speaker.available else 'unavailable'}",
                  f"Speech recognition: {stt_status() or 'ready'}"]
        if self.ctx.store:
            s = self.ctx.store
            lines += ["", f"Project: {s.path}", f"Changes recorded: {s.revision_count()}",
                      f"Snapshots: {len(self.ctx.backups.list())} in {self.ctx.backups.folder}"]
        QMessageBox.information(self, "Diagnostics", "\n".join(lines))

    def _about(self) -> None:
        QMessageBox.about(self, APP_DISPLAY_NAME, f"<b>{APP_DISPLAY_NAME}</b> {APP_VERSION}<br>"
                          "An offline, voice-friendly interviewer and story bible for writers.<br><br>"
                          "Everything stays on your computer. No AI text generation — "
                          "PyWriter asks, listens and organizes; the writing is yours.<br><br>"
                          "<small>Copyright © 2023-2026 sharxbyte. Free software under the GNU GPL v3 or "
                          "later, with no warranty: see TERMS-OF-USE.md and LICENSE in the program folder. "
                          "Anything you write with PyWriter is yours to publish and sell.<br>"
                          "<a href='https://github.com/sharxbyte/FoolsGold_Pywriter'>"
                          "github.com/sharxbyte/FoolsGold_Pywriter</a></small>")

    def closeEvent(self, e) -> None:
        self.ctx.set("ui/talk_visible", self.talk_dock.isVisible())
        self.ctx.speaker.stop()
        self.ctx.listener.stop_and_wait()
        self.close_project()
        super().closeEvent(e)
