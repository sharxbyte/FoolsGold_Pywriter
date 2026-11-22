"""Talk panel: describe the story in your own words (typed or spoken) and the
interpreter files the details into the story bible."""
from __future__ import annotations

import html

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QCheckBox, QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout, QWidget

from ..nlu import HELP_TEXT, Interpreter
from ..voice import tidy_dictation
from .common import EntityBrowser, LevelMeter, linkify


class TalkPanel(QWidget):
    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.interp: Interpreter | None = None
        self._listening = False
        self._awaiting_speech_end = False
        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 6, 6, 6)
        self.log = EntityBrowser(ctx)
        self.log.entity_clicked.connect(ctx.bus.open_entity.emit)
        lay.addWidget(self.log, 1)
        row = QHBoxLayout()
        self.input = QLineEdit()
        self.input.setPlaceholderText("Tell me about your story…  (try: Mara is the protagonist)")
        self.input.returnPressed.connect(self.send)
        row.addWidget(self.input, 1)
        send = QPushButton("Send")
        send.clicked.connect(self.send)
        row.addWidget(send)
        lay.addLayout(row)
        vr = QHBoxLayout()
        self.mic = QPushButton("🎤 Talk")
        self.mic.setCheckable(True)
        self.mic.setToolTip("Speak instead of typing. Each pause sends what you said.")
        self.mic.toggled.connect(self._toggle_mic)
        vr.addWidget(self.mic)
        self.meter = LevelMeter()
        vr.addWidget(self.meter)
        self.speak_replies = QCheckBox("Read replies aloud")
        self.speak_replies.setChecked(ctx.get("talk/speak_replies", True, bool))
        self.speak_replies.toggled.connect(lambda v: ctx.set("talk/speak_replies", v))
        vr.addWidget(self.speak_replies)
        vr.addStretch(1)
        self.status = QLabel()
        self.status.setObjectName("muted")
        vr.addWidget(self.status)
        lay.addLayout(vr)

        ctx.listener.final.connect(self._on_final)
        ctx.listener.partial.connect(self._on_partial)
        ctx.listener.level.connect(lambda v: self._listening and self.meter.set_level(v))
        ctx.listener.error.connect(lambda m: self._listening and self.status.setText(m))
        ctx.speaker.finished.connect(self._on_speech_done)
        ctx.assistant.result.connect(self._on_ai_result)
        self._pending_ai = None
        ctx.bus.reloaded.connect(self.reset)
        self.reset()

    def reset(self) -> None:
        if not self.ctx.store:
            return
        self.interp = Interpreter(self.ctx.store, self.ctx.library)
        self.log.clear()
        for row in self.ctx.store.conversation(60):
            self._append(row["speaker"], row["text"], log=False)
        if not self.ctx.store.conversation(1):
            self._append("pywriter", HELP_TEXT, log=False)

    def set_focus_entity(self, eid: str | None) -> None:
        if self.interp and eid:
            self.interp.set_focus(eid)

    def _append(self, who: str, text: str, log: bool = True) -> None:
        store = self.ctx.store
        body = linkify(store, text) if store else html.escape(text)
        if who == "writer":
            self.log.append(f"<p style='margin:6px 0'><b>You:</b> {body}</p>")
        else:
            self.log.append(f"<p style='margin:6px 0;color:#8a5a20'><b>PyWriter:</b> {body}</p>")
        sb = self.log.verticalScrollBar()
        sb.setValue(sb.maximum())

    def send(self, text: str | None = None, spoken: bool = False) -> None:
        text = (text if isinstance(text, str) else self.input.text()).strip()
        if not text or not self.interp:
            return
        self.input.clear()
        self._append("writer", text)
        if not spoken:
            self.ctx.transcript.write("Typed in Talk", text)
        asst = self.ctx.assistant
        if asst.usable and not self.interp.wants_rules(text):
            # let the local AI interpret free-form remarks (off the UI thread)
            self.ctx.store.log_conversation("writer", text)
            self.status.setText("Thinking…")
            self._pending_ai = (asst.request(text, self.interp.known_names(), self.interp.recent(),
                                             self.interp.focus_name()), text, spoken)
            return
        try:
            reply = self.interp.handle(text, spoken=spoken)
        except Exception as e:  # never crash the conversation
            import traceback
            traceback.print_exc()
            self.ctx.store.add_note(self.ctx.store.project_entity().id, text, source="talk")
            self._append("pywriter", f"Sorry, I got confused ({e}). I've kept what you said as a note.")
            return
        self._show_reply(reply)

    def _on_ai_result(self, rid: int, actions) -> None:
        pending = getattr(self, "_pending_ai", None)
        if not pending or pending[0] != rid:
            return
        self._pending_ai = None
        _, text, spoken = pending
        self.status.setText("Listening…" if self._listening else "")
        reply = None
        try:
            reply = self.interp.handle_actions(text, actions, spoken=spoken) if actions else None
            if reply is None:  # fall back to the built-in rules
                self.interp._spoken = spoken
                reply = self.interp._handle(text)
                if reply.text:
                    self.ctx.store.log_conversation("pywriter", reply.text)
        except Exception as e:
            import traceback
            traceback.print_exc()
            self.ctx.store.add_note(self.ctx.store.project_entity().id, text, source="talk")
            self._append("pywriter", f"Sorry, I got confused ({e}). I've kept what you said as a note.")
            return
        self._show_reply(reply)

    def _show_reply(self, reply) -> None:
        if reply.text and not self.speak_replies.isChecked():
            self.ctx.transcript.write("PyWriter replied", reply.text)  # spoken replies are logged as said
        if reply.text:
            self._append("pywriter", reply.text)
            if self.speak_replies.isChecked() and self.ctx.speaker.available:
                if self._listening:
                    self.ctx.listener.stop()
                    self._awaiting_speech_end = True
                self.ctx.speaker.say(reply.text)
        if reply.open_entity:
            self.ctx.bus.open_entity.emit(reply.open_entity)
        if reply.start_interview:
            kind, eid = reply.start_interview
            pack = self.ctx.library.pack_for_kind(kind, self.ctx.store.project_type)
            if pack:
                if self._listening:
                    self.mic.setChecked(False)
                self.ctx.bus.start_interview.emit(pack.id, eid or "")

    # ---------------------------------------------------------------- voice
    def _toggle_mic(self, on: bool) -> None:
        if on:
            if not self.ctx.listener.available:
                from ..voice import stt_status
                self.status.setText(stt_status())
                self.mic.setChecked(False)
                return
            self._listening = True
            self.ctx.listener.start()
            self.status.setText("Listening…")
        else:
            self._listening = False
            self._awaiting_speech_end = False
            self.ctx.listener.stop()
            self.status.setText("")

    def stop_listening(self) -> None:
        if self.mic.isChecked():
            self.mic.setChecked(False)

    def _on_partial(self, text: str) -> None:
        if self._listening:
            self.status.setText(f"Hearing: {text}")

    def _on_final(self, text: str) -> None:
        if not self._listening or self._awaiting_speech_end:
            return
        self.status.setText("Listening…")
        self.send(tidy_dictation(text, [n for _, _, n in self.ctx.store.all_names()]), spoken=True)

    def _on_speech_done(self) -> None:
        if self._awaiting_speech_end:
            self._awaiting_speech_end = False
            if self._listening:
                self.ctx.listener.start()
