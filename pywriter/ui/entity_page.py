"""Entry page (character sheet, location sheet, ...).

* Sheet tab: read-only, every mention of another entry is a link; hover for a short
  bio, click to open it.
* Edit tab: every interview question as an editable field, grouped by section.
  Changes save automatically (and are recorded in the change history).
* Side panel: connections, places inside (for locations), mentions, notes.
"""
from __future__ import annotations

import html

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (QCheckBox, QComboBox, QCompleter, QDialog, QDialogButtonBox, QFormLayout,
                               QFrame, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
                               QMessageBox, QPlainTextEdit, QPushButton, QScrollArea, QSplitter, QTabWidget,
                               QVBoxLayout, QWidget, QInputDialog)

from ..engine import Interview
from ..library import LEVEL_LABELS, evaluate
from ..store import KINDS, RELATIONS, TIER_LABELS
from ..summary import spoken_summary, subtitle
from .common import EntityBrowser, LinkLabel, linkify


class AutoTextEdit(QPlainTextEdit):
    focus_lost = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setTabChangesFocus(True)
        self.textChanged.connect(self._fit)
        self._fit()

    def _fit(self):
        lines = max(2, min(12, self.document().size().height() + 1))
        fm = self.fontMetrics()
        self.setFixedHeight(int(lines * fm.lineSpacing() + 14))

    def focusOutEvent(self, e):
        super().focusOutEvent(e)
        self.focus_lost.emit()


class LinkDialog(QDialog):
    def __init__(self, ctx, entity_id: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Add connection")
        self.ctx = ctx
        lay = QFormLayout(self)
        self.target = QComboBox()
        self.target.setEditable(True)
        self.target.setInsertPolicy(QComboBox.NoInsert)
        for e in ctx.store.entities():
            if e.id != entity_id and e.kind != "project":
                self.target.addItem(f"{e.label}  ({KINDS[e.kind][1]})", e.id)
        self.target.completer().setFilterMode(Qt.MatchContains)
        self.target.completer().setCompletionMode(QCompleter.PopupCompletion)
        lay.addRow("Connected to:", self.target)
        self.relation = QComboBox()
        self.relation.setEditable(True)
        self.relation.addItems(sorted(RELATIONS))
        self.relation.setCurrentText("related to")
        lay.addRow("They are this entry's:", self.relation)
        hint = QLabel("Read as: “<target> is this entry's <relation>”, e.g. Tomas is Mara's sibling.")
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        lay.addRow(hint)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addRow(bb)


class EntityPage(QWidget):
    def __init__(self, ctx, entity_id: str, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.entity_id = entity_id
        self._editors: dict[str, QWidget] = {}
        self._dirty: set[str] = set()
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(900)
        self._save_timer.timeout.connect(self.save_pending)
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.setInterval(150)
        self._refresh_timer.timeout.connect(self.refresh)

        root = QVBoxLayout(self)
        head = QHBoxLayout()
        tl = QVBoxLayout()
        self.title = QLabel()
        self.title.setObjectName("h1")
        self.subtitle = QLabel()
        self.subtitle.setObjectName("muted")
        tl.addWidget(self.title)
        tl.addWidget(self.subtitle)
        head.addLayout(tl, 1)
        self.reinterview_btn = QPushButton("🎙 Re-interview")
        self.reinterview_btn.setToolTip("Run the interview again with current answers filled in")
        self.reinterview_btn.clicked.connect(self._reinterview)
        head.addWidget(self.reinterview_btn)
        self.read_btn = QPushButton("🔊 Read aloud")
        self.read_btn.clicked.connect(lambda: ctx.speaker.say(spoken_summary(ctx.store, self.entity_id)))
        head.addWidget(self.read_btn)
        self.rename_btn = QPushButton("Rename")
        self.rename_btn.clicked.connect(self._rename)
        head.addWidget(self.rename_btn)
        self.delete_btn = QPushButton("Delete")
        self.delete_btn.clicked.connect(self._delete)
        head.addWidget(self.delete_btn)
        root.addLayout(head)

        split = QSplitter(Qt.Horizontal)
        self.tabs = QTabWidget()
        self.sheet = EntityBrowser(ctx)
        self.sheet.entity_clicked.connect(ctx.bus.open_entity.emit)
        self.tabs.addTab(self.sheet, "Sheet")
        edit_wrap = QWidget()
        ew = QVBoxLayout(edit_wrap)
        ew.setContentsMargins(0, 0, 0, 0)
        self.show_empty = QCheckBox("Show unanswered questions")
        self.show_empty.setChecked(True)
        self.show_empty.toggled.connect(self._build_form)
        ew.addWidget(self.show_empty)
        self.form_scroll = QScrollArea()
        self.form_scroll.setWidgetResizable(True)
        ew.addWidget(self.form_scroll, 1)
        self.tabs.addTab(edit_wrap, "Edit")
        split.addWidget(self.tabs)

        side = QWidget()
        sl = QVBoxLayout(side)
        sl.setContentsMargins(6, 0, 0, 0)
        h = QLabel("Connections")
        h.setObjectName("h2")
        sl.addWidget(h)
        self.links_box = QVBoxLayout()
        sl.addLayout(self.links_box)
        lb = QHBoxLayout()
        add_link = QPushButton("+ Connect")
        add_link.clicked.connect(self._add_link)
        lb.addWidget(add_link)
        self.unlink_combo = QComboBox()
        self.unlink_combo.setToolTip("Choose a connection to remove")
        lb.addWidget(self.unlink_combo, 1)
        rm = QPushButton("Remove")
        rm.clicked.connect(self._remove_link)
        lb.addWidget(rm)
        sl.addLayout(lb)
        self.children_head = QLabel("Places inside")
        self.children_head.setObjectName("h2")
        sl.addWidget(self.children_head)
        self.children_box = QVBoxLayout()
        sl.addLayout(self.children_box)
        self.add_child_btn = QPushButton("+ Add a place inside")
        self.add_child_btn.clicked.connect(self._add_child)
        sl.addWidget(self.add_child_btn)
        mh = QLabel("Mentioned in")
        mh.setObjectName("h2")
        sl.addWidget(mh)
        self.mentions_box = QVBoxLayout()
        sl.addLayout(self.mentions_box)
        nh = QLabel("Notes")
        nh.setObjectName("h2")
        sl.addWidget(nh)
        self.notes = QListWidget()
        self.notes.setWordWrap(True)
        self.notes.setMaximumHeight(180)
        sl.addWidget(self.notes)
        nl = QHBoxLayout()
        self.note_edit = QLineEdit()
        self.note_edit.setPlaceholderText("Add a note…")
        self.note_edit.returnPressed.connect(self._add_note)
        nl.addWidget(self.note_edit, 1)
        dn = QPushButton("Delete note")
        dn.clicked.connect(self._delete_note)
        nl.addWidget(dn)
        sl.addLayout(nl)
        sl.addStretch(1)
        side_scroll = QScrollArea()
        side_scroll.setWidgetResizable(True)
        side_scroll.setWidget(side)
        split.addWidget(side_scroll)
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 2)
        root.addWidget(split, 1)

        ctx.bus.entity_changed.connect(self._on_changed)
        ctx.bus.links_changed.connect(self._on_changed)
        self.refresh()
        self._build_form()

    # ---------------------------------------------------------------- data
    @property
    def entity(self):
        return self.ctx.store.get(self.entity_id)

    @property
    def pack(self):
        e = self.entity
        if not e:
            return None
        if e.kind == "project":
            return None
        return self.ctx.library.pack_for_kind(e.kind, self.ctx.store.project_type)

    def project_packs(self):
        return self.ctx.library.project_packs(self.ctx.store.project_type)

    def _packs(self):
        e = self.entity
        if e and e.kind == "project":
            return self.project_packs()
        return [p for p in [self.pack] if p]

    def _on_changed(self, eid: str) -> None:
        # refresh if this entry, or anything shown on it, changed
        self._refresh_timer.start()

    # ---------------------------------------------------------------- refresh
    def refresh(self) -> None:
        e = self.entity
        if not e:
            return
        if e.deleted:
            self.title.setText(f"{e.label} (deleted)")
        else:
            self.title.setText(e.label)
        self.subtitle.setText(f"{subtitle(self.ctx.store, e)}  ·  {e.id}  ·  updated {e.updated.replace('T', ' ')}")
        self.reinterview_btn.setEnabled(bool(self._packs()))
        self._render_sheet(e)
        self._render_links(e)
        self._render_children(e)
        self._render_mentions(e)
        self._render_notes(e)
        self._sync_form_values(e)

    def _answers_for_conditions(self, e) -> dict:
        a = dict(e.fields)
        a["name"], a["tier"] = e.name, e.tier
        return a

    def _project_ctx(self) -> dict:
        p = self.ctx.store.project_entity()
        d = dict(p.fields)
        d["name"] = p.name
        d["type"] = self.ctx.store.project_type
        return d

    def _render_sheet(self, e) -> None:
        store = self.ctx.store
        parts = []
        anc = store.ancestors(e.id)
        if anc:
            crumbs = " › ".join(f"<a href='entity://{a.id}'>{html.escape(a.label)}</a>" for a in reversed(anc))
            parts.append(f"<p style='color:gray'>Within: {crumbs}</p>")
        used = {"name", "tier", "parent"}
        answers = self._answers_for_conditions(e)
        for pack in self._packs():
            for s in pack.sections:
                rows = []
                for q in s.questions:
                    used.add(q.key)
                    v = e.fields.get(q.key, "")
                    if not v or q.key in ("name", "parent"):
                        continue
                    if q.key == "tier":
                        continue
                    if q.type in ("choice", "yesno"):
                        v = q.option_label(v)
                        if e.fields.get(q.key + "_details"):
                            v += " — " + e.fields[q.key + "_details"]
                            used.add(q.key + "_details")
                    if q.key == "level":
                        v = LEVEL_LABELS.get(e.fields[q.key], v)
                    rows.append(f"<tr><td valign='top' width='30%' style='padding:3px 12px 3px 0;color:gray'>"
                                f"{html.escape(q.display_label)}</td>"
                                f"<td style='padding:3px 0'>{linkify(store, v, exclude=e.id)}</td></tr>")
                if rows:
                    parts.append(f"<h3>{html.escape(s.title)}</h3><table width='100%'>{''.join(rows)}</table>")
        extra = [(k, v) for k, v in e.fields.items() if k not in used and not k.startswith("_") and v]
        if extra:
            rows = "".join(f"<tr><td valign='top' style='padding:3px 12px 3px 0;color:gray'>"
                           f"{html.escape(k.replace('_', ' ').capitalize())}</td>"
                           f"<td>{linkify(store, v, exclude=e.id)}</td></tr>" for k, v in extra)
            parts.append(f"<h3>Other details</h3><table width='100%'>{rows}</table>")
        if not parts:
            parts.append("<p style='color:gray'>No details yet. Click <b>Re-interview</b> to answer questions, "
                         "use the <b>Edit</b> tab, or describe this entry in <b>Talk</b> mode.</p>")
        self.sheet.setHtml("".join(parts))

    def _clear(self, lay) -> None:
        while lay.count():
            it = lay.takeAt(0)
            if it.widget():
                it.widget().deleteLater()

    def _render_links(self, e) -> None:
        self._clear(self.links_box)
        self.unlink_combo.clear()
        groups: dict[str, list] = {}
        for link, other, rel in self.ctx.store.links_for(e.id):
            groups.setdefault(rel, []).append((link, other))
        if not groups:
            lab = QLabel("No connections yet.")
            lab.setObjectName("muted")
            self.links_box.addWidget(lab)
        for rel in sorted(groups):
            row = QWidget()
            rl = QHBoxLayout(row)
            rl.setContentsMargins(0, 0, 0, 0)
            rlab = QLabel(rel.capitalize() + ":")
            rlab.setObjectName("muted")
            rlab.setMinimumWidth(110)
            rl.addWidget(rlab)
            for link, other in groups[rel]:
                o = self.ctx.store.get(other, with_fields=False)
                if not o:
                    continue
                chip = LinkLabel(self.ctx, other, o.label)
                chip.clicked.connect(self.ctx.bus.open_entity.emit)
                rl.addWidget(chip)
                self.unlink_combo.addItem(f"{rel}: {o.label}", (link.src, link.dst, link.relation))
            rl.addStretch(1)
            self.links_box.addWidget(row)

    def _render_children(self, e) -> None:
        is_loc = e.kind == "location"
        self.children_head.setVisible(is_loc)
        self.add_child_btn.setVisible(is_loc)
        self._clear(self.children_box)
        if not is_loc:
            return
        kids = self.ctx.store.children(e.id)
        if not kids:
            lab = QLabel("None yet.")
            lab.setObjectName("muted")
            self.children_box.addWidget(lab)
        for k in kids:
            k_full = self.ctx.store.get(k.id)
            lvl = LEVEL_LABELS.get(k_full.fields.get("level", ""), "")
            chip = LinkLabel(self.ctx, k.id, f"{k.label}" + (f"  ({lvl})" if lvl else ""))
            chip.clicked.connect(self.ctx.bus.open_entity.emit)
            self.children_box.addWidget(chip)

    def _render_mentions(self, e) -> None:
        self._clear(self.mentions_box)
        if not e.name or len(e.name) < 3:
            return
        names = [e.name.lower()] + [a.strip().lower() for a in e.fields.get("aliases", "").split(",") if a.strip()]
        linked = {o for _, o, _ in self.ctx.store.links_for(e.id)}
        found = []
        for other in self.ctx.store.entities(with_fields=True):
            if other.id == e.id or other.id in linked:
                continue
            blob = " ".join(other.fields.values()).lower()
            if any(n in blob for n in names):
                found.append(other)
        if not found:
            lab = QLabel("Not mentioned elsewhere yet.")
            lab.setObjectName("muted")
            self.mentions_box.addWidget(lab)
        for o in found[:30]:
            chip = LinkLabel(self.ctx, o.id, f"{o.label}  ({KINDS[o.kind][1]})")
            chip.clicked.connect(self.ctx.bus.open_entity.emit)
            self.mentions_box.addWidget(chip)

    def _render_notes(self, e) -> None:
        self.notes.clear()
        for n in self.ctx.store.notes_for(e.id):
            it = QListWidgetItem(f"{n['text']}\n— {n['created'].replace('T', ' ')} ({n['source']})")
            it.setData(Qt.UserRole, n["id"])
            self.notes.addItem(it)

    # ---------------------------------------------------------------- edit form
    def _build_form(self) -> None:
        self.save_pending()
        e = self.entity
        if not e:
            return
        self._editors.clear()
        w = QWidget()
        lay = QVBoxLayout(w)
        answers = self._answers_for_conditions(e)
        proj = self._project_ctx()
        # name always first
        top = QGroupBox("Identity")
        tf = QFormLayout(top)
        name_ed = QLineEdit(e.name)
        name_ed.editingFinished.connect(lambda: self._save_field("name", name_ed.text()))
        tf.addRow("Name", name_ed)
        self._editors["name"] = name_ed
        if e.kind == "character":
            tier = QComboBox()
            for k in ("", "primary", "secondary", "tertiary"):
                tier.addItem(TIER_LABELS[k], k)
            tier.setCurrentIndex(max(0, tier.findData(e.tier)))
            tier.currentIndexChanged.connect(lambda _: (self._save_field("tier", tier.currentData()),
                                                        QTimer.singleShot(0, self._build_form)))
            tf.addRow("Importance", tier)
            self._editors["tier"] = tier
        if e.kind == "location":
            parent = QComboBox()
            parent.addItem("(none — top level)", "")
            for loc in self.ctx.store.entities("location"):
                if loc.id != e.id:
                    parent.addItem(loc.label, loc.id)
            parent.setCurrentIndex(max(0, parent.findData(e.parent_id or "")))
            parent.currentIndexChanged.connect(lambda _: self._save_field("parent", parent.currentData()))
            tf.addRow("Located in", parent)
            self._editors["parent"] = parent
        lay.addWidget(top)
        shown = {"name", "tier", "parent"}
        for pack in self._packs():
            for s in pack.sections:
                box = QGroupBox(s.title)
                f = QFormLayout(box)
                f.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)
                count = 0
                for q in s.questions:
                    if q.key in shown:
                        continue
                    shown.add(q.key)
                    val = e.fields.get(q.key, "")
                    applies = (not s.when or evaluate(s.when, answers, proj)) and evaluate(q.when, answers, proj)
                    if not val and (not applies or not self.show_empty.isChecked()):
                        continue
                    ed = self._make_editor(q, val)
                    lab = QLabel(q.display_label)
                    lab.setToolTip(q.ask)
                    lab.setWordWrap(True)
                    f.addRow(lab, ed)
                    count += 1
                if count:
                    lay.addWidget(box)
        extra = [(k, v) for k, v in e.fields.items() if k not in shown and not k.startswith("_")]
        box = QGroupBox("Other details")
        f = QFormLayout(box)
        for k, v in extra:
            ed = AutoTextEdit()
            ed.setPlainText(v)
            self._wire_text(k, ed)
            f.addRow(k.replace("_", " ").capitalize(), ed)
        addf = QPushButton("+ Add a custom field")
        addf.clicked.connect(self._add_custom_field)
        f.addRow(addf)
        lay.addWidget(box)
        lay.addStretch(1)
        self.form_scroll.setWidget(w)

    def _make_editor(self, q, val: str) -> QWidget:
        if q.type in ("choice", "yesno"):
            cb = QComboBox()
            cb.setEditable(q.allow_other and q.type == "choice")
            cb.addItem("", "")
            for o in q.options:
                cb.addItem(o.label, o.value)
            i = cb.findData(val)
            if i >= 0:
                cb.setCurrentIndex(i)
            elif val:
                cb.setEditText(val)
            cb.setToolTip(q.ask)

            def save(_=None, cb=cb, key=q.key):
                d = cb.currentData()
                txt = cb.currentText()
                self._save_field(key, d if d is not None and cb.itemText(cb.currentIndex()) == txt else txt)
            cb.activated.connect(save)
            if cb.isEditable():
                cb.lineEdit().editingFinished.connect(save)
            self._editors[q.key] = cb
            return cb
        if q.type in ("text", "number", "entity", "entities"):
            ed = QLineEdit(val)
            ed.setToolTip(q.ask)
            if q.type in ("entity", "entities"):
                ed.setPlaceholderText("Names, separated by commas" if q.type == "entities" else "Name")
            ed.editingFinished.connect(lambda key=q.key, ed=ed: self._save_field(key, ed.text()))
            self._editors[q.key] = ed
            return ed
        ed = AutoTextEdit()
        ed.setPlainText(val)
        ed.setToolTip(q.ask)
        self._wire_text(q.key, ed)
        return ed

    def _wire_text(self, key: str, ed: AutoTextEdit) -> None:
        ed.textChanged.connect(lambda: (self._dirty.add(key), self._save_timer.start()))
        ed.focus_lost.connect(self.save_pending)
        self._editors[key] = ed

    def save_pending(self) -> None:
        for key in list(self._dirty):
            ed = self._editors.get(key)
            if isinstance(ed, QPlainTextEdit):
                self._save_field(key, ed.toPlainText(), refresh=False)
        self._dirty.clear()

    def _save_field(self, key: str, value: str, refresh: bool = True) -> None:
        e = self.entity
        if not e:
            return
        pack = self.pack
        q = pack.question(key) if pack else None
        if not q:
            for p in self._packs():
                q = p.question(key)
                if q:
                    pack = p
                    break
        if q and q.type in ("entity", "entities") and pack:
            iv = Interview(pack, self.ctx.store, self.entity_id)
            iv.answers[key] = value
            iv.commit(source="edit")
        else:
            self.ctx.store.set_field(self.entity_id, key, value, source="edit")

    def _sync_form_values(self, e) -> None:
        """Update editors from the database without clobbering what's being typed."""
        for key, ed in self._editors.items():
            if ed.hasFocus() or key in self._dirty:
                continue
            val = e.get(key)
            if isinstance(ed, QPlainTextEdit):
                if ed.toPlainText() != val:
                    ed.blockSignals(True)
                    ed.setPlainText(val)
                    ed.blockSignals(False)
            elif isinstance(ed, QLineEdit):
                if ed.text() != val:
                    ed.setText(val)
            elif isinstance(ed, QComboBox):
                i = ed.findData(val)
                ed.blockSignals(True)
                if i >= 0:
                    ed.setCurrentIndex(i)
                elif ed.isEditable():
                    ed.setEditText(val)
                ed.blockSignals(False)

    def _add_custom_field(self) -> None:
        name, ok = QInputDialog.getText(self, "Custom field", "Field name (e.g. Favorite weapon):")
        if ok and name.strip():
            key = name.strip().lower().replace(" ", "_")
            self.ctx.store.set_field(self.entity_id, key, "(fill me in)", source="edit")
            self._build_form()

    # ---------------------------------------------------------------- actions
    def _reinterview(self) -> None:
        packs = self._packs()
        if not packs:
            return
        pack = packs[0]
        if len(packs) > 1:
            names = [p.title for p in packs]
            choice, ok = QInputDialog.getItem(self, "Re-interview", "Which interview?", names, 0, False)
            if not ok:
                return
            pack = packs[names.index(choice)]
        self.save_pending()
        self.ctx.bus.start_interview.emit(pack.id, self.entity_id)

    def _rename(self) -> None:
        e = self.entity
        name, ok = QInputDialog.getText(self, "Rename", "New name:", text=e.name)
        if ok and name.strip():
            self.ctx.store.set_field(e.id, "name", name.strip(), source="edit")

    def _delete(self) -> None:
        e = self.entity
        if e.kind == "project":
            return
        if QMessageBox.question(self, "Delete", f"Delete {e.label}? You can restore it from History.") \
                == QMessageBox.Yes:
            self.ctx.store.delete_entity(e.id)

    def _add_link(self) -> None:
        d = LinkDialog(self.ctx, self.entity_id, self)
        if d.exec() and d.target.currentData():
            self.ctx.store.link(self.entity_id, d.target.currentData(), d.relation.currentText() or "related to")

    def _remove_link(self) -> None:
        data = self.unlink_combo.currentData()
        if data:
            self.ctx.store.unlink(*data)

    def _add_child(self) -> None:
        pack = self.ctx.library.pack_for_kind("location", self.ctx.store.project_type)
        if pack:
            self.ctx.bus.start_interview.emit(pack.id, "parent:" + self.entity_id)

    def _add_note(self) -> None:
        t = self.note_edit.text().strip()
        if t:
            self.ctx.store.add_note(self.entity_id, t)
            self.note_edit.clear()

    def _delete_note(self) -> None:
        it = self.notes.currentItem()
        if it:
            self.ctx.store.delete_note(it.data(Qt.UserRole))
