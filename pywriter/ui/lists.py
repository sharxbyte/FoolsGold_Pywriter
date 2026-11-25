"""Browse panels: one per kind of entry, plus the project overview."""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (QAbstractItemView, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QMenu,
                               QMessageBox, QPushButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
                               QGridLayout, QFrame)

from ..library import LEVEL_LABELS
from ..store import KINDS, TIER_LABELS
from ..summary import tooltip_html
from .common import KIND_COLORS


class EntityTree(QTreeWidget):
    def __init__(self, ctx, kind: str, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.kind = kind
        self.setHeaderHidden(False)
        self.setMouseTracking(True)
        self.setAlternatingRowColors(True)
        self.setUniformRowHeights(False)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        cols = {"character": ["Name", "Role", "Occupation"],
                "location": ["Name", "Level", "Type"],
                "event": ["#", "Event", "When"],
                "scene": ["Scene", "Synopsis"]}.get(kind, ["Name", "Summary"])
        self.setHeaderLabels(cols)
        self.setColumnWidth(0, 240)
        if kind == "event":
            self.setColumnWidth(0, 50)
            self.setColumnWidth(1, 260)
            self.setDragDropMode(QAbstractItemView.InternalMove)
            self.setSelectionMode(QAbstractItemView.SingleSelection)
        self.itemEntered.connect(self._hover)

    def _hover(self, item: QTreeWidgetItem, col: int) -> None:
        eid = item.data(0, Qt.UserRole)
        if eid and not item.toolTip(0):
            tip = tooltip_html(self.ctx.store, eid)
            for c in range(self.columnCount()):
                item.setToolTip(c, tip)

    def dropEvent(self, e):
        super().dropEvent(e)
        if self.kind == "event":
            # renumber in the dropped order
            with self.ctx.store.batch():
                for i in range(self.topLevelItemCount()):
                    eid = self.topLevelItem(i).data(0, Qt.UserRole)
                    if eid:
                        self.ctx.store.set_field(eid, "order", str(i + 1), source="timeline")


def _order_value(e) -> float:
    try:
        return float(e.fields.get("order") or 1e9)
    except ValueError:
        return 1e9


class EntityListPanel(QWidget):
    def __init__(self, ctx, kind: str, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.kind = kind
        lay = QVBoxLayout(self)
        head = QHBoxLayout()
        h = QLabel(KINDS[kind][2])
        h.setObjectName("h1")
        head.addWidget(h)
        head.addStretch(1)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search…")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self.refresh)
        self.search.setMaximumWidth(260)
        head.addWidget(self.search)
        lay.addLayout(head)
        btns = QHBoxLayout()
        self.interview_btn = QPushButton(f"🎙 New {KINDS[kind][1].lower()} (interview)")
        self.interview_btn.setObjectName("primary")
        self.interview_btn.clicked.connect(lambda: self._start_interview(None))
        btns.addWidget(self.interview_btn)
        quick = QPushButton("+ Quick add")
        quick.setToolTip("Add just a name now; fill in details later")
        quick.clicked.connect(self._quick_add)
        btns.addWidget(quick)
        btns.addStretch(1)
        hint = QLabel("Double-click to open · hover for a summary" +
                      (" · drag to reorder" if kind == "event" else ""))
        hint.setObjectName("muted")
        hint.setWordWrap(True)  # never let a hint force the window wider than the screen
        hint.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        btns.addWidget(hint, 1)
        lay.addLayout(btns)
        self.tree = EntityTree(ctx, kind)
        self.tree.itemActivated.connect(self._open)
        self.tree.customContextMenuRequested.connect(self._menu)
        lay.addWidget(self.tree, 1)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(120)
        self._timer.timeout.connect(self.refresh)
        ctx.bus.entity_changed.connect(lambda _: self._timer.start())
        ctx.bus.reloaded.connect(self._timer.start)
        self.interview_btn.setEnabled(self._pack() is not None)

    def _pack(self):
        return self.ctx.library.pack_for_kind(self.kind, self.ctx.store.project_type) if self.ctx.store else None

    def refresh(self) -> None:
        if not self.ctx.store:
            return
        expanded = set()
        for i in range(self.tree.topLevelItemCount()):
            self._collect_expanded(self.tree.topLevelItem(i), expanded)
        first_time = self.tree.topLevelItemCount() == 0
        self.tree.clear()
        q = self.search.text().strip().lower()
        ents = self.ctx.store.entities(self.kind, with_fields=True)
        if q:
            ents = [e for e in ents if q in e.name.lower() or any(q in v.lower() for v in e.fields.values())]
        color = KIND_COLORS.get(self.kind)
        if self.kind == "character":
            groups = {}
            for e in ents:
                groups.setdefault(e.tier, []).append(e)
            for tier in ("primary", "secondary", "tertiary", ""):
                if tier not in groups:
                    continue
                g = QTreeWidgetItem([f"{TIER_LABELS[tier]} characters ({len(groups[tier])})"])
                g.setFirstColumnSpanned(True)
                f = g.font(0)
                f.setBold(True)
                g.setFont(0, f)
                g.setData(1, Qt.UserRole, "group:" + tier)
                self.tree.addTopLevelItem(g)
                for e in sorted(groups[tier], key=lambda e: e.name.lower()):
                    g.addChild(self._item(e, [e.label, e.fields.get("story_role", ""), e.fields.get("occupation", "")]))
                g.setExpanded(first_time or ("group:" + tier) in expanded or bool(q))
        elif self.kind == "location":
            by_parent: dict = {}
            ids = {e.id for e in ents}
            parent_of = {e.id: e.parent_id for e in ents}

            def in_loop(eid: str) -> bool:
                # "A is inside B, B is inside A" (or a place inside itself) would hide
                # both places from the tree, so such places are shown at the top level
                seen, cur = {eid}, parent_of.get(eid)
                while cur in ids:
                    if cur in seen:
                        return True
                    seen.add(cur)
                    cur = parent_of.get(cur)
                return False

            for e in ents:
                pid = e.parent_id if e.parent_id in ids and not in_loop(e.id) else None
                by_parent.setdefault(pid, []).append(e)

            def add(parent_item, pid, depth=0):
                for e in sorted(by_parent.get(pid, []), key=lambda x: x.name.lower()):
                    it = self._item(e, [e.label, LEVEL_LABELS.get(e.fields.get("level", ""), ""),
                                        e.fields.get("place_type", "")])
                    (parent_item.addChild(it) if parent_item else self.tree.addTopLevelItem(it))
                    if depth < 12:
                        add(it, e.id, depth + 1)
                    it.setExpanded(first_time or e.id in expanded or bool(q))
            add(None, None)
        elif self.kind == "event":
            for e in sorted(ents, key=lambda e: (_order_value(e), e.sort_order)):
                o = e.fields.get("order", "")
                self.tree.addTopLevelItem(self._item(e, [o, e.label, e.fields.get("when", "")], drop=False))
        else:
            from ..summary import brief_rows
            for e in ents:
                rows = brief_rows(self.ctx.store, e, 1)
                self.tree.addTopLevelItem(self._item(e, [e.label, rows[0][1] if rows else ""]))
        if not ents:
            it = QTreeWidgetItem([f"No {KINDS[self.kind][2].lower()} yet — start an interview, quick add, "
                                  f"or just talk about them in Talk mode."])
            it.setFirstColumnSpanned(True)
            it.setFlags(Qt.NoItemFlags)
            self.tree.addTopLevelItem(it)

    def _collect_expanded(self, item, out: set) -> None:
        if item.isExpanded():
            out.add(item.data(0, Qt.UserRole) or item.data(1, Qt.UserRole))
        for i in range(item.childCount()):
            self._collect_expanded(item.child(i), out)

    def _item(self, e, cols, drop=True) -> QTreeWidgetItem:
        it = QTreeWidgetItem([str(c) for c in cols])
        it.setData(0, Qt.UserRole, e.id)
        flags = Qt.ItemIsEnabled | Qt.ItemIsSelectable
        if self.kind == "event":
            flags |= Qt.ItemIsDragEnabled
        it.setFlags(flags)
        return it

    def _open(self, item: QTreeWidgetItem, col: int = 0) -> None:
        eid = item.data(0, Qt.UserRole)
        if eid:
            self.ctx.bus.open_entity.emit(eid)

    def _start_interview(self, eid: str | None) -> None:
        pack = self._pack()
        if pack:
            self.ctx.bus.start_interview.emit(pack.id, eid or "")

    def _quick_add(self) -> None:
        name, ok = QInputDialog.getText(self, f"New {KINDS[self.kind][1].lower()}", "Name:")
        if ok and name.strip():
            existing = self.ctx.store.find_by_name(name, self.kind)
            if existing:
                QMessageBox.information(self, "Already exists", f"{existing.label} already exists.")
                self.ctx.bus.open_entity.emit(existing.id)
                return
            eid = self.ctx.store.create_entity(self.kind, name.strip())
            self.ctx.bus.open_entity.emit(eid)

    def _menu(self, pos) -> None:
        item = self.tree.itemAt(pos)
        eid = item.data(0, Qt.UserRole) if item else None
        if not eid:
            return
        m = QMenu(self)
        m.addAction("Open", lambda: self.ctx.bus.open_entity.emit(eid))
        if self._pack():
            m.addAction("Re-interview", lambda: self._start_interview(eid))
        if self.kind == "location" and self._pack():
            m.addAction("Add a place inside…",
                        lambda: self.ctx.bus.start_interview.emit(self._pack().id, "parent:" + eid))
        m.addSeparator()
        m.addAction("Delete", lambda: self._delete(eid))
        m.exec(self.tree.viewport().mapToGlobal(pos))

    def _delete(self, eid: str) -> None:
        e = self.ctx.store.get(eid)
        if QMessageBox.question(self, "Delete", f"Delete {e.label}? You can restore it from History.") \
                == QMessageBox.Yes:
            self.ctx.store.delete_entity(eid)


class OverviewPanel(QWidget):
    guided = Signal()

    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        lay = QVBoxLayout(self)
        self.title = QLabel()
        self.title.setObjectName("h1")
        lay.addWidget(self.title)
        self.sub = QLabel()
        self.sub.setObjectName("muted")
        self.sub.setWordWrap(True)
        lay.addWidget(self.sub)
        row = QHBoxLayout()
        g = QPushButton("🎙  Start the Guided Story Interview")
        g.setObjectName("primary")
        g.setMinimumHeight(44)
        g.setToolTip("Walks you through the whole project: the big picture, world, characters, places, plot and more")
        g.clicked.connect(self.guided.emit)
        row.addWidget(g)
        self.project_btns = QHBoxLayout()
        row.addLayout(self.project_btns)
        row.addStretch(1)
        lay.addLayout(row)
        self.stats = QGridLayout()
        lay.addLayout(self.stats)
        tip = QLabel(
            "<b>Ways to work</b><ul>"
            "<li><b>Interviews</b> ask you questions one at a time. Turn on <b>Narration mode</b> (F5) to do them "
            "hands-free: questions are read aloud and your spoken answers recorded.</li>"
            "<li><b>Talk</b> (Ctrl+T) lets you simply describe your story — “Mara is the protagonist. She lives "
            "in Port Vell.” — and files the details for you.</li>"
            "<li><b>Map</b> shows how everything connects; <b>Manuscript</b> is where you write, with dictation "
            "and read-aloud.</li>"
            "<li>Everything saves automatically. Every change is kept in <b>History</b>, and snapshots are kept in "
            "the project's <i>backups</i> folder.</li></ul>")
        tip.setWordWrap(True)
        tip.setTextFormat(Qt.RichText)
        lay.addWidget(tip)
        self.page_holder = QVBoxLayout()
        lay.addLayout(self.page_holder, 1)
        ctx.bus.entity_changed.connect(lambda _: self.refresh())
        ctx.bus.reloaded.connect(self.refresh)

    def refresh(self) -> None:
        s = self.ctx.store
        if not s:
            return
        self.title.setText(s.title)
        p = s.project_entity()
        premise = p.fields.get("premise") or p.fields.get("thesis") or p.fields.get("subject_significance") or ""
        self.sub.setText(f"{s.project_type} project · {s.folder}" + (f"\n\n{premise}" if premise else ""))
        while self.project_btns.count():
            w = self.project_btns.takeAt(0).widget()
            if w:
                w.deleteLater()
        for pack in self.ctx.library.project_packs(s.project_type):
            b = QPushButton(pack.title)
            b.clicked.connect(lambda _=False, pid=pack.id: self.ctx.bus.start_interview.emit(pid, ""))
            self.project_btns.addWidget(b)
        while self.stats.count():
            w = self.stats.takeAt(0).widget()
            if w:
                w.deleteLater()
        col = 0
        for kind, (_, single, plural) in KINDS.items():
            if kind in ("project",):
                continue
            n = len(s.entities(kind))
            if n == 0 and not self.ctx.library.pack_for_kind(kind, s.project_type) and kind != "scene":
                continue
            card = QFrame()
            card.setFrameShape(QFrame.StyledPanel)
            cl = QVBoxLayout(card)
            num = QLabel(str(n))
            num.setObjectName("h1")
            num.setAlignment(Qt.AlignCenter)
            lab = QLabel(plural)
            lab.setAlignment(Qt.AlignCenter)
            lab.setObjectName("muted")
            cl.addWidget(num)
            cl.addWidget(lab)
            self.stats.addWidget(card, col // 6, col % 6)  # wrap so small screens still fit
            col += 1
