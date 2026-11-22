"""The interview window.

Modes:
* Typing: answer in the box, Ctrl+Enter or Next to continue.
* Dictate: speech is typed into the answer box as you talk.
* Narration (hands-free): each question is read aloud, then PyWriter listens.
  - Say "next question, confirm" (or finished / continue / proceed + confirm / yes)
    to move on. Saying just "next question" makes PyWriter ask you to confirm.
  - After ~10 seconds of silence it checks whether you're finished (or, if
    nothing was said, offers to skip). Another silence pauses narration.
  - Also: "go back", "repeat the question", "read my answer", "skip question",
    "scratch that", "stop listening", "end interview".
Answers are saved to the project after every step, so nothing is lost.
"""
from __future__ import annotations

from PySide6.QtCore import QStringListModel, Qt, QTimer, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (QButtonGroup, QCompleter, QDialog, QFrame, QHBoxLayout, QLabel, QLineEdit,
                               QMessageBox, QPlainTextEdit, QProgressBar, QPushButton, QScrollArea, QSizePolicy,
                               QStackedWidget, QToolButton, QVBoxLayout, QWidget, QComboBox)

from ..engine import CommitResult, Interview, resolve_name
from ..library import Pack, Question
from ..store import KINDS, split_list
from ..names import needs_spelling_check, parse_spelling, spell_out
from ..voice import is_no, is_yes, parse_command
from .common import DictationTarget, LevelMeter, center_on_screen


WAITING_STATES = ("confirm", "confirm_skip", "confirm_spell", "end")


class MultiNameEdit(QLineEdit):
    """Line edit with completion on the last comma-separated name."""

    def __init__(self, names: list[str], multi: bool, parent=None):
        super().__init__(parent)
        self.multi = multi
        self._model = QStringListModel(sorted(set(names), key=str.lower))
        self._comp = QCompleter(self._model, self)
        self._comp.setCaseSensitivity(Qt.CaseInsensitive)
        self._comp.setFilterMode(Qt.MatchContains)
        self._comp.setWidget(self)
        self._comp.activated.connect(self._insert)
        self.textEdited.connect(self._update)

    def _segment(self) -> str:
        return self.text().split(",")[-1].strip() if self.multi else self.text().strip()

    def _update(self, _):
        seg = self._segment()
        if len(seg) >= 1:
            self._comp.setCompletionPrefix(seg)
            if self._comp.completionCount():
                self._comp.complete()
                return
        self._comp.popup().hide()

    def _insert(self, name: str):
        if self.multi:
            parts = [p.strip() for p in self.text().split(",")[:-1] if p.strip()]
            parts.append(name)
            self.setText(", ".join(parts) + ", ")
        else:
            self.setText(name)


class InterviewDialog(QDialog):
    finished_interview = Signal(object)  # CommitResult

    def __init__(self, ctx, pack: Pack, entity_id: str | None = None, preset: dict | None = None,
                 parent=None, narration: bool | None = None):
        super().__init__(parent)
        self.ctx = ctx
        self.iv = Interview(pack, ctx.store, entity_id, preset)
        self.result_commit: CommitResult | None = None
        self.wants_another = False
        self.setWindowTitle(pack.title)
        self.setWindowFlag(Qt.WindowMaximizeButtonHint, True)

        # voice state
        self.speaker = ctx.speaker
        self.listener = ctx.listener
        self.silence_timeout = ctx.get("voice/silence_seconds", 10, int)
        self.state = "idle"          # idle | speaking | listening | confirm | confirm_skip | end
        self._after_speech = None    # callable to run when TTS finishes
        self._prompted_silence = False
        self._last_inserted = ""
        self._dictating = False
        self._spell_queue: list[tuple[str, str, list[str]]] = []  # (as written, reason, choices)

        self._build()
        self.speaker.finished.connect(self._on_speech_done)
        self.listener.final.connect(self._on_final)
        self.listener.partial.connect(self._on_partial)
        self.listener.silence.connect(self._on_silence)
        self.listener.level.connect(self.meter.set_level)
        self.listener.error.connect(self._on_listen_error)

        center_on_screen(self, 0.5, 0.5)
        self._show_question()
        if narration if narration is not None else ctx.get("voice/narration_default", False, bool):
            QTimer.singleShot(300, lambda: self.narrate_btn.setChecked(True))
        elif pack.intro and not entity_id:
            self.status.setText(pack.intro)

    # ================================================================ layout
    def _build(self) -> None:
        root = QVBoxLayout(self)
        top = QHBoxLayout()
        self.section = QLabel()
        self.section.setObjectName("section")
        top.addWidget(self.section)
        top.addStretch(1)
        self.jump = QComboBox()
        self.jump.setToolTip("Jump to a section")
        for s in self.iv.pack.sections:
            self.jump.addItem(s.title, s.id)
        self.jump.activated.connect(self._jump_section)
        top.addWidget(self.jump)
        root.addLayout(top)
        self.progress = QProgressBar()
        self.progress.setTextVisible(True)
        self.progress.setFixedHeight(16)
        root.addWidget(self.progress)

        self.stack = QStackedWidget()
        root.addWidget(self.stack, 1)

        # ---- question page
        qpage = QWidget()
        ql = QVBoxLayout(qpage)
        ql.setContentsMargins(4, 12, 4, 4)
        self.question = QLabel()
        self.question.setObjectName("question")
        self.question.setWordWrap(True)
        self.question.setTextInteractionFlags(Qt.TextSelectableByMouse)
        ql.addWidget(self.question)
        self.hint = QLabel()
        self.hint.setObjectName("muted")
        self.hint.setWordWrap(True)
        ql.addWidget(self.hint)
        self.choices_box = QWidget()
        self.choices_lay = QVBoxLayout(self.choices_box)
        self.choices_lay.setContentsMargins(0, 6, 0, 6)
        ql.addWidget(self.choices_box)
        self.answer_holder = QVBoxLayout()
        ql.addLayout(self.answer_holder, 1)
        self.ref_info = QLabel()
        self.ref_info.setObjectName("muted")
        self.ref_info.setWordWrap(True)
        ql.addWidget(self.ref_info)
        self.stack.addWidget(qpage)

        # ---- end page
        epage = QWidget()
        el = QVBoxLayout(epage)
        self.end_label = QLabel()
        self.end_label.setObjectName("question")
        self.end_label.setWordWrap(True)
        el.addWidget(self.end_label)
        self.end_detail = QLabel()
        self.end_detail.setWordWrap(True)
        self.end_detail.setObjectName("muted")
        el.addWidget(self.end_detail)
        el.addStretch(1)
        eb = QHBoxLayout()
        self.another_yes = QPushButton("Yes, add another")
        self.another_yes.setObjectName("primary")
        self.another_yes.clicked.connect(lambda: self._end(True))
        self.another_no = QPushButton("No, I'm done")
        self.another_no.clicked.connect(lambda: self._end(False))
        eb.addStretch(1)
        eb.addWidget(self.another_no)
        eb.addWidget(self.another_yes)
        el.addLayout(eb)
        self.stack.addWidget(epage)

        # ---- voice bar
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        root.addWidget(line)
        vb = QHBoxLayout()
        self.read_q_btn = QPushButton("🔊 Read question")
        self.read_q_btn.setToolTip("Read the question aloud (F2)")
        self.read_q_btn.clicked.connect(lambda: self._speak(self.question.text()))
        vb.addWidget(self.read_q_btn)
        self.read_a_btn = QPushButton("🔊 Read answer")
        self.read_a_btn.setToolTip("Read your answer aloud (F3)")
        self.read_a_btn.clicked.connect(lambda: self._speak(self._answer_text() or "There's no answer yet."))
        vb.addWidget(self.read_a_btn)
        self.dictate_btn = QPushButton("🎤 Dictate")
        self.dictate_btn.setCheckable(True)
        self.dictate_btn.setToolTip("Type with your voice (F4)")
        self.dictate_btn.toggled.connect(self._toggle_dictate)
        vb.addWidget(self.dictate_btn)
        self.narrate_btn = QPushButton("🎧 Narration mode")
        self.narrate_btn.setCheckable(True)
        self.narrate_btn.setToolTip("Hands-free: questions are read aloud and your spoken answers recorded (F5)")
        self.narrate_btn.toggled.connect(self._toggle_narration)
        vb.addWidget(self.narrate_btn)
        self.meter = LevelMeter()
        vb.addWidget(self.meter)
        self.status = QLabel()
        self.status.setObjectName("muted")
        self.status.setWordWrap(True)
        vb.addWidget(self.status, 1)
        root.addLayout(vb)

        # ---- nav bar
        nb = QHBoxLayout()
        self.back_btn = QPushButton("◀ Back")
        self.back_btn.clicked.connect(self.go_back)
        nb.addWidget(self.back_btn)
        self.skip_btn = QPushButton("Skip")
        self.skip_btn.clicked.connect(self.skip)
        nb.addWidget(self.skip_btn)
        nb.addStretch(1)
        self.finish_btn = QPushButton("Save && finish")
        self.finish_btn.setToolTip("Save everything answered so far and end this interview")
        self.finish_btn.clicked.connect(self.finish)
        nb.addWidget(self.finish_btn)
        self.next_btn = QPushButton("Next ▶")
        self.next_btn.setObjectName("primary")
        self.next_btn.setToolTip("Ctrl+Enter")
        self.next_btn.clicked.connect(self.go_next)
        nb.addWidget(self.next_btn)
        root.addLayout(nb)

        QShortcut(QKeySequence("Ctrl+Return"), self, self.go_next)
        QShortcut(QKeySequence("Ctrl+Enter"), self, self.go_next)
        QShortcut(QKeySequence("Alt+Left"), self, self.go_back)
        QShortcut(QKeySequence("F2"), self, self.read_q_btn.click)
        QShortcut(QKeySequence("F3"), self, self.read_a_btn.click)
        QShortcut(QKeySequence("F4"), self, self.dictate_btn.toggle)
        QShortcut(QKeySequence("F5"), self, self.narrate_btn.toggle)

    # ================================================================ question display
    @staticmethod
    def _drop(w) -> None:
        w.hide()
        w.setParent(None)
        w.deleteLater()

    def _clear_answer_widgets(self) -> None:
        while self.answer_holder.count():
            w = self.answer_holder.takeAt(0).widget()
            if w:
                self._drop(w)
        while self.choices_lay.count():
            item = self.choices_lay.takeAt(0)
            if item.widget():
                self._drop(item.widget())
            elif item.layout():
                lay = item.layout()
                while lay.count():
                    w = lay.takeAt(0).widget()
                    if w:
                        self._drop(w)
        self.choice_group = None
        self.answer = None

    def _fit_question(self) -> None:
        w = max(200, self.question.width())
        self.question.setMinimumHeight(self.question.heightForWidth(w))

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._fit_question()

    def _show_question(self) -> None:
        q = self.iv.current
        if q is None:
            self._show_end()
            return
        self.stack.setCurrentIndex(0)
        self.state = "idle"
        self._resume_state = "idle"
        self._clear_answer_widgets()
        self.question.setText(self.iv.text())
        self._fit_question()
        sec_title = self.iv.section_title()
        self.section.setText(sec_title.upper())
        idx = self.jump.findData(q.section.id if q.section else "")
        if idx >= 0:
            self.jump.setCurrentIndex(idx)
        n, total = self.iv.progress()
        self.progress.setMaximum(max(1, total))
        self.progress.setValue(n)
        self.progress.setFormat(f"Question {n} of {total}")
        self.hint.setText(q.help)
        self.hint.setVisible(bool(q.help))
        self.ref_info.clear()
        current = self.iv.answers.get(q.key, "")

        if q.type in ("choice", "yesno"):
            self.choice_group = QButtonGroup(self)
            self.choice_group.setExclusive(True)
            row = QHBoxLayout() if len(q.options) <= 4 else None
            box = row if row is not None else self.choices_lay
            for o in q.options:
                b = QPushButton(o.label)
                b.setCheckable(True)
                b.setProperty("value", o.value)
                b.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
                if o.value == current:
                    b.setChecked(True)
                b.clicked.connect(self._on_choice_clicked)
                self.choice_group.addButton(b)
                box.addWidget(b)
            if row is not None:
                row.addStretch(1)
                self.choices_lay.addLayout(row)
            self.choices_box.setVisible(True)
            if q.allow_other and q.type == "choice":
                other = QLineEdit()
                other.setPlaceholderText("…or type your own answer")
                if current and not any(o.value == current for o in q.options):
                    other.setText(current)
                other.textEdited.connect(lambda _: self._uncheck_choices())
                other.returnPressed.connect(self.go_next)
                self.answer = other
                self.answer_holder.addWidget(other)
                self.answer_holder.addStretch(1)
            elif q.type == "yesno":
                details = QLineEdit()
                details.setPlaceholderText("…add details if you like (optional)")
                if current and current not in ("yes", "no"):
                    details.setText(current)
                details.returnPressed.connect(self.go_next)
                self.answer = details
                self.answer_holder.addWidget(details)
                self.answer_holder.addStretch(1)
            else:
                self.answer = None
                self.answer_holder.addStretch(1)
        elif q.type in ("entity", "entities"):
            self.choices_box.setVisible(False)
            names = [n for _, k, n in self.ctx.store.all_names() if not q.kind or k == q.kind]
            ed = MultiNameEdit(names, multi=q.type == "entities")
            ed.setPlaceholderText("Type names, separated by commas" if q.type == "entities" else "Type a name")
            ed.setText(current)
            ed.textChanged.connect(self._update_ref_info)
            ed.returnPressed.connect(self.go_next)
            self.answer = ed
            self.answer_holder.addWidget(ed)
            self.answer_holder.addStretch(1)
            self._update_ref_info()
        elif q.type in ("text", "number"):
            self.choices_box.setVisible(False)
            ed = QLineEdit()
            ed.setText(current)
            ed.returnPressed.connect(self.go_next)
            self.answer = ed
            self.answer_holder.addWidget(ed)
            self.answer_holder.addStretch(1)
        else:
            self.choices_box.setVisible(False)
            ed = QPlainTextEdit()
            ed.setPlainText(current)
            ed.setTabChangesFocus(True)
            self.answer = ed
            self.answer_holder.addWidget(ed, 1)
        if self.answer is not None:
            self.answer.setFocus()
            if isinstance(self.answer, QPlainTextEdit):
                c = self.answer.textCursor()
                c.movePosition(c.MoveOperation.End)
                self.answer.setTextCursor(c)
        self.back_btn.setEnabled(self.iv.progress()[0] > 1)
        self._prompted_silence = False
        self._spell_queue.clear()
        if self.narrate_btn.isChecked():
            self._narrate_current()

    def _uncheck_choices(self) -> None:
        if self.choice_group:
            self.choice_group.setExclusive(False)
            for b in self.choice_group.buttons():
                b.setChecked(False)
            self.choice_group.setExclusive(True)

    def _on_choice_clicked(self) -> None:
        if isinstance(self.answer, QLineEdit) and self.iv.current and self.iv.current.type == "choice":
            self.answer.clear()
        # choosing an option is an answer: move on promptly when typing
        if not self.narrate_btn.isChecked():
            QTimer.singleShot(150, self.go_next)

    def _update_ref_info(self) -> None:
        q = self.iv.current
        if not q or q.type not in ("entity", "entities") or not isinstance(self.answer, QLineEdit):
            return
        names = split_list(self.answer.text()) if q.type == "entities" else \
            ([self.answer.text().strip()] if self.answer.text().strip() else [])
        known, new = [], []
        for n in names:
            (known if resolve_name(self.ctx.store, n, q.kind or None) else new).append(n)
        bits = []
        if known:
            bits.append("Linked: " + ", ".join(known))
        if new:
            kind = KINDS.get(q.kind or "character", ("", "entry"))[1].lower()
            bits.append(f"New {kind}{'s' if len(new) > 1 else ''} to be created: " + ", ".join(new))
        self.ref_info.setText("   ·   ".join(bits))

    def _answer_text(self) -> str:
        q = self.iv.current
        if q is None:
            return ""
        if q.type in ("choice", "yesno"):
            if self.choice_group and self.choice_group.checkedButton():
                val = self.choice_group.checkedButton().property("value")
                if q.type == "yesno" and isinstance(self.answer, QLineEdit) and self.answer.text().strip():
                    # keep yes/no as the value; details go in a companion field
                    return val
                return val
            return self.answer.text().strip() if isinstance(self.answer, QLineEdit) else ""
        if isinstance(self.answer, QPlainTextEdit):
            return self.answer.toPlainText().strip()
        if isinstance(self.answer, QLineEdit):
            return self.answer.text().strip()
        return ""

    def _store_current(self) -> None:
        q = self.iv.current
        if q is None:
            return
        self.iv.answer(self._answer_text())
        if q.type == "yesno" and isinstance(self.answer, QLineEdit):
            detail = self.answer.text().strip()
            if detail:
                self.iv.answers[q.key + "_details"] = detail
        self._autosave()

    def _autosave(self, final: bool = False) -> CommitResult | None:
        try:
            res = self.iv.commit(final=final)
            if res:
                self.result_commit = res if not self.result_commit else self._merge(self.result_commit, res)
            return res
        except Exception as e:  # never lose the dialog over a save error
            self.status.setText(f"⚠ Couldn't save: {e}")
            return None

    @staticmethod
    def _merge(a: CommitResult, b: CommitResult) -> CommitResult:
        a.created += [c for c in b.created if c not in a.created]
        a.spawns += b.spawns
        a.entity_id = b.entity_id
        return a

    # ================================================================ navigation
    def go_next(self) -> None:
        if self.stack.currentIndex() != 0:
            return
        q = self.iv.current
        if q and q.required and not self._answer_text():
            self.status.setText("This one is needed before we continue.")
            if self.narrate_btn.isChecked():
                self._speak("I need an answer to this one before we continue. " + self.question.text(),
                            then=self._listen)
            return
        had_entity = self.iv.entity_id
        self._store_current()
        if not had_entity and self.iv.adopted:
            e = self.ctx.store.get(self.iv.adopted, with_fields=False)
            self.status.setText(f"{e.label} was already in your project, so I'm adding to that entry.")
        self.iv.next()
        self._show_question()

    def go_back(self) -> None:
        if self.stack.currentIndex() == 1:
            self.iv.back()
            self._show_question()
            return
        self._store_current()
        self.iv.back()
        self._show_question()

    def skip(self) -> None:
        if self.iv.current and self.iv.current.required:
            self.status.setText("This question can't be skipped.")
            return
        self.iv.next()
        self._show_question()

    def _jump_section(self, idx: int) -> None:
        sid = self.jump.itemData(idx)
        self._store_current()
        for q in self.iv.pack.questions:
            if q.section and q.section.id == sid and self.iv.is_visible(q):
                self.iv.current = q
                self._show_question()
                return
        self.status.setText("That section doesn't apply based on your answers so far.")

    def finish(self) -> None:
        if self.stack.currentIndex() == 0:
            self._store_current()
        self.iv.current = None
        self._show_end()

    def _show_end(self) -> None:
        res = self._autosave(final=True)
        self.stack.setCurrentIndex(1)
        self.progress.setValue(self.progress.maximum())
        self.progress.setFormat("Complete")
        self.section.setText("SAVED")
        name = self.iv.answers.get("name", "") or "this entry"
        outro = self.iv.pack.outro.replace("{name}", name) if self.iv.pack.outro else "Saved."
        another = self.iv.pack.another
        self.end_label.setText(f"{outro}\n\n{another}" if another else outro)
        detail = []
        if self.result_commit and self.result_commit.created:
            names = [self.ctx.store.get(c).label for c in self.result_commit.created if self.ctx.store.get(c)]
            detail.append("New entries created from your answers (you can interview them later): "
                          + ", ".join(names))
        self.end_detail.setText("\n".join(detail))
        self.another_yes.setVisible(bool(another))
        self.another_no.setText("No, I'm done" if another else "Close")
        self.next_btn.setEnabled(False)
        self.skip_btn.setEnabled(False)
        self.finish_btn.setEnabled(False)
        self.back_btn.setEnabled(True)
        self.state = "end"
        if self.narrate_btn.isChecked():
            self._speak(self.end_label.text().replace("\n", " "), then=self._listen if another else None)

    def _end(self, another: bool) -> None:
        self.wants_another = another
        self._shutdown_voice()
        self.accept()

    def reject(self) -> None:
        if self.stack.currentIndex() == 0:
            self._store_current()
            self._autosave(final=False)
        self._shutdown_voice()
        super().reject()

    def closeEvent(self, e) -> None:
        if self.stack.currentIndex() == 0:
            self._store_current()
        self._shutdown_voice()
        super().closeEvent(e)

    def _shutdown_voice(self) -> None:
        for sig, slot in ((self.speaker.finished, self._on_speech_done), (self.listener.final, self._on_final),
                          (self.listener.partial, self._on_partial), (self.listener.silence, self._on_silence),
                          (self.listener.level, self.meter.set_level), (self.listener.error, self._on_listen_error)):
            try:
                sig.disconnect(slot)
            except (RuntimeError, TypeError):
                pass
        self.speaker.stop()
        self.listener.stop()

    # ================================================================ voice
    def _speak(self, text: str, then=None) -> None:
        if not self.speaker.available:
            self.status.setText("Text-to-speech isn't available on this system.")
            if then:
                then()
            return
        self.listener.stop()
        # remember what we're waiting for (a yes/no, a spelling...) so speaking doesn't erase it
        if self.state != "speaking":
            self._resume_state = self.state if self.state in WAITING_STATES else "idle"
        self.state = "speaking"
        self._after_speech = then
        self.speaker.say(text)

    def _on_speech_done(self) -> None:
        cb, self._after_speech = self._after_speech, None
        if self.state == "speaking":
            self.state = getattr(self, "_resume_state", "idle")
        if cb:
            cb()
        elif self._dictating:
            self.listener.start()

    def _listen(self) -> None:
        if not (self.narrate_btn.isChecked() or self._dictating):
            return
        if self.state not in ("confirm", "confirm_skip", "end", "confirm_spell"):
            self.state = "listening"
        if self.stack.currentIndex() == 1:
            self.state = "end"
        self._prompted_silence = self.state in ("confirm", "confirm_skip")
        self._silence_base = None
        self.listener.start()
        self.status.setText("Listening… say “next question, confirm” when you're done."
                            if self.state == "listening" else "Listening for yes or no…")

    def _narrate_current(self) -> None:
        q = self.iv.current
        if not q:
            return
        text = self.question.text()
        if q.type in ("choice",) and q.options and len(q.options) <= 7:
            pass  # options are already listed in the question text
        existing = self._answer_text()
        if existing:
            text += f" The current answer is: {existing if q.type not in ('choice', 'yesno') else q.option_label(existing)}."\
                    " Keep it by saying next question, confirm, or add to it."
        self._speak(text, then=self._listen)

    def _toggle_narration(self, on: bool) -> None:
        if on:
            if not self.listener.available:
                self.status.setText(self.listener_unavailable_text())
                self.narrate_btn.setChecked(False)
                QMessageBox.information(self, "Speech recognition", self.listener_unavailable_text())
                return
            self.dictate_btn.setChecked(False)
            if self.stack.currentIndex() == 0:
                self._narrate_current()
            else:
                self._speak(self.end_label.text().replace("\n", " "), then=self._listen)
        else:
            self.state = "idle"
            self.speaker.stop()
            self.listener.stop()
            self.status.setText("Narration off.")

    def _toggle_dictate(self, on: bool) -> None:
        if on:
            if not self.listener.available:
                self.dictate_btn.setChecked(False)
                QMessageBox.information(self, "Speech recognition", self.listener_unavailable_text())
                return
            self.narrate_btn.setChecked(False)
            self._dictating = True
            self.state = "listening"
            self.listener.start()
            self.status.setText("Dictating… speak your answer.")
        else:
            self._dictating = False
            self.listener.stop()
            self.status.setText("Dictation off.")

    @staticmethod
    def listener_unavailable_text() -> str:
        from ..voice import stt_status
        return stt_status() or "Speech recognition isn't available."

    def _on_listen_error(self, msg: str) -> None:
        self.status.setText(f"⚠ {msg}")

    def _on_partial(self, text: str) -> None:
        if self.state in ("listening", "confirm", "confirm_skip", "end"):
            self.status.setText(f"Hearing: {text}")

    def _on_silence(self, seconds: float) -> None:
        if not self.narrate_btn.isChecked() or self.state == "speaking":
            return
        if seconds < self.silence_timeout:
            return
        if self.state == "listening" and not self._prompted_silence:
            self._prompted_silence = True
            if self._answer_text():
                self.state = "confirm"
                self._speak("Are you finished with this question? Say yes to move on, or keep talking.",
                            then=self._listen)
            else:
                self.state = "confirm_skip"
                self._speak("I haven't heard an answer yet. Would you like to skip this question? "
                            "Say yes to skip, or go ahead and answer.", then=self._listen)
        elif self.state in ("confirm", "confirm_skip", "end") and seconds >= self.silence_timeout * 2:
            self._pause_narration()

    def _pause_narration(self) -> None:
        self.listener.stop()
        self.state = "idle"
        self.status.setText("Narration paused after a long silence. Press F5 twice or click Narration mode to resume.")
        self.narrate_btn.blockSignals(True)
        self.narrate_btn.setChecked(False)
        self.narrate_btn.blockSignals(False)
        self._speak("I'll pause here. Turn narration back on whenever you're ready.")

    def _on_final(self, text: str) -> None:
        if self.state == "speaking" or not (self.narrate_btn.isChecked() or self._dictating):
            return
        cmd, rest = parse_command(text)

        # ----- end page: another?
        if self.stack.currentIndex() == 1:
            if is_yes(text):
                self._end(True)
            elif is_no(text) or cmd in ("finish_interview", "advance_confirmed"):
                self._end(False)
            return

        # ----- confirming the spelling of a spoken name
        if self.state == "confirm_spell" and self._spell_queue:
            self._handle_spelling_reply(text, cmd)
            return

        # ----- waiting for confirmation
        if self.state in ("confirm", "confirm_skip"):
            if is_yes(text) or cmd == "advance_confirmed":
                if self.state == "confirm_skip":
                    self.skip()
                else:
                    self.go_next()
                return
            if is_no(text):
                self.state = "listening"
                self._prompted_silence = False
                self._speak("Okay, go ahead.", then=self._listen)
                return
            self.state = "listening"  # they kept talking: treat as more answer
            self._prompted_silence = False

        if cmd == "advance_confirmed":
            if rest:
                self._insert(rest)
            if not self._answer_text() and self.iv.current and self.iv.current.required:
                self._speak("I need an answer to this one. " + self.question.text(), then=self._listen)
                return
            self.go_next()
            return
        if cmd == "advance":
            if rest:
                self._insert(rest)
            if self.narrate_btn.isChecked():
                self.state = "confirm"
                self._speak("Shall I move to the next question? Say yes or confirm.", then=self._listen)
            return
        if cmd == "back":
            self.go_back()
            return
        if cmd == "repeat":
            self._narrate_current() if self.narrate_btn.isChecked() else self._speak(self.question.text())
            return
        if cmd == "read_answer":
            self._speak(self._answer_text() or "There's no answer yet.", then=self._listen)
            return
        if cmd == "skip":
            self.skip()
            return
        if cmd == "scratch":
            self._scratch()
            return
        if cmd == "pause":
            self.narrate_btn.setChecked(False)
            self.dictate_btn.setChecked(False)
            return
        if cmd == "finish_interview":
            self.finish()
            return

        # ----- plain dictation
        q = self.iv.current
        if q and q.type in ("choice", "yesno") and self.choice_group:
            val = q.match_option(text)
            if val:
                for b in self.choice_group.buttons():
                    if b.property("value") == val:
                        b.setChecked(True)
                if isinstance(self.answer, QLineEdit) and q.type == "choice":
                    self.answer.clear()
                if self.narrate_btn.isChecked():
                    self.state = "confirm"
                    self._speak(f"I heard {q.option_label(val)}. Is that right?", then=self._listen)
                else:
                    self.status.setText(f"Selected: {q.option_label(val)}")
                return
        if q and (q.key == "name" or q.type in ("entity", "entities")):
            text = self._titlecase_names(text)
            self._insert(text)
            self._queue_spelling_checks(q, text)
            return
        self._insert(text)

    # ---------------------------------------------------------------- spelling
    @staticmethod
    def _titlecase_names(text: str) -> str:
        small = {"of", "the", "and", "de", "von", "van", "la", "le", "du"}
        words = text.strip(" .").split()
        return " ".join(w if (i and w.lower() in small) else w[:1].upper() + w[1:] for i, w in enumerate(words))

    def _queue_spelling_checks(self, q, text: str) -> None:
        names = split_list(text) if q.type == "entities" else [text.strip(" .")]
        kind = self.iv.pack.kind if q.key == "name" else (q.kind or "character")
        for n in names:
            if q.type in ("entity", "entities") and resolve_name(self.ctx.store, n, q.kind or None):
                continue  # already in the project, so the spelling is known
            check = needs_spelling_check(n, person=kind == "character")
            if check:
                self._spell_queue.append((n, check[0], check[1]))
        if self._spell_queue and self.narrate_btn.isChecked():
            self._ask_spelling()

    def _ask_spelling(self) -> None:
        if not self._spell_queue:
            self.state = "listening"
            self._prompted_silence = False
            self._speak("Thanks. Carry on, or say next question, confirm.", then=self._listen)
            return
        name, reason, choices = self._spell_queue[0]
        self.state = "confirm_spell"
        if reason == "variants":
            opts = "   ".join(f"{i + 1}: {c}" for i, c in enumerate(choices))
            self.status.setText(f"Which spelling?  {opts}   (say the number, or spell it)")
            spoken = " ".join(f"Number {i + 1}: {spell_out(c)}" for i, c in enumerate(choices))
            self._speak(f"There are a few common spellings of {name}. {spoken} Say the number you want, "
                        f"or spell it out letter by letter.", then=self._listen)
        else:
            self.status.setText(f"I wrote \u201c{name}\u201d. Say yes if that's right, or spell it letter by letter.")
            self._speak(f"I've written that name as {spell_out(name)} Is that right? Say yes, or spell it "
                        f"out letter by letter.", then=self._listen)

    def _replace_in_answer(self, old: str, new: str) -> None:
        if old == new or self.answer is None:
            return
        get = self.answer.toPlainText if isinstance(self.answer, QPlainTextEdit) else self.answer.text
        t = get()
        i = t.lower().rfind(old.lower())
        if i < 0:
            return
        t = t[:i] + new + t[i + len(old):]
        if isinstance(self.answer, QPlainTextEdit):
            self.answer.setPlainText(t)
        else:
            self.answer.setText(t)
        self._update_ref_info()

    def _handle_spelling_reply(self, text: str, cmd) -> None:
        name, reason, choices = self._spell_queue[0]
        low = text.lower().strip()
        nums = {"one": 1, "first": 1, "1": 1, "two": 2, "to": 2, "too": 2, "second": 2, "2": 2,
                "three": 3, "third": 3, "3": 3, "four": 4, "for": 4, "fourth": 4, "4": 4,
                "five": 5, "fifth": 5, "5": 5}
        chosen = None
        if reason == "variants":
            words = low.replace("number", " ").split()
            if len(words) <= 2:
                for w in words:
                    if w in nums and nums[w] <= len(choices):
                        chosen = choices[nums[w] - 1]
                        break
            if not chosen:
                for c in choices:
                    if low == c.lower():
                        chosen = c
        spelled = parse_spelling(text)
        if spelled and not chosen:
            parts = name.split()
            n = len(spelled.split())
            chosen = spelled if n >= len(parts) else " ".join([spelled] + parts[n:])
        if chosen:
            self._replace_in_answer(name, chosen)
            self._spell_queue.pop(0)
            self.status.setText(f"Spelling set to: {chosen}")
            self._speak(f"Got it, {chosen}.", then=self._ask_spelling)
            return
        if is_yes(text) or cmd == "advance_confirmed":
            self._spell_queue.pop(0)
            if cmd == "advance_confirmed" and not self._spell_queue:
                self.state = "listening"
                self.go_next()
                return
            self._ask_spelling()
            return
        if is_no(text):
            self._speak("Okay. Please spell it out letter by letter, for example: M, A, R, A.", then=self._listen)
            return
        self._speak("Sorry, I didn't catch that. Say yes if the spelling is right, or spell it letter by letter.",
                    then=self._listen)

    def _insert(self, text: str) -> None:
        if self.answer is None:
            return
        self._last_inserted = text
        DictationTarget(self.answer).insert(text)
        self.status.setText(f"Added: {text}")

    def _scratch(self) -> None:
        if not self._last_inserted or self.answer is None:
            return
        from ..voice import tidy_dictation
        piece = tidy_dictation(self._last_inserted)
        if isinstance(self.answer, QPlainTextEdit):
            t = self.answer.toPlainText()
            i = t.rfind(piece)
            if i >= 0:
                self.answer.setPlainText((t[:i] + t[i + len(piece):]).rstrip())
        elif isinstance(self.answer, QLineEdit):
            t = self.answer.text()
            p = piece.rstrip(".")
            i = t.rfind(p)
            if i >= 0:
                self.answer.setText((t[:i] + t[i + len(p):]).rstrip())
        self._last_inserted = ""
        self.status.setText("Removed the last thing you said.")
