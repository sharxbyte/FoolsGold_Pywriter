"""Settings: appearance, voice and backups."""
from __future__ import annotations

from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout,
                               QGroupBox, QHBoxLayout, QLabel, QMessageBox, QProgressDialog, QPushButton,
                               QSlider, QSpinBox, QVBoxLayout)
from PySide6.QtCore import Qt

from .. import audio
from .. import names as names_mod
from ..voice import (LARGE_MODEL, MODELS, PIPER_VOICES, ModelDownloader, PiperDownloader, engines,
                     input_devices, installed_models, model_path, piper_available, piper_installed, stt_status)
from .theme import THEMES


def download_model(parent, ctx) -> None:
    from PySide6.QtWidgets import QInputDialog
    installed = model_path()
    names = list(MODELS)
    labels = [MODELS[n] + ("  (installed)" if installed and installed.name == n else "") for n in names]
    choice, ok = QInputDialog.getItem(
        parent, "Download speech model",
        "Speech recognition needs a one-time download from alphacephei.com.\n"
        "After that it works fully offline. Which model would you like?", labels,
        1 if installed else 0, False)
    if not ok:
        return
    model = names[labels.index(choice)]
    if installed and installed.name == model:
        QMessageBox.information(parent, "Speech model", f"That model is already installed:\n{installed}")
        return
    dlg = QProgressDialog("Downloading speech model…", "Cancel", 0, 100, parent)
    dlg.setWindowTitle("Speech model")
    dlg.setAutoClose(False)
    dlg.setMinimumDuration(0)
    th = ModelDownloader(parent, model)

    def prog(done, total):
        if total:
            dlg.setValue(int(done * 100 / total))
            dlg.setLabelText(f"Downloading speech model… {done // 1_000_000} of {total // 1_000_000} MB")

    def finished(err):
        dlg.close()
        if err:
            QMessageBox.warning(parent, "Speech model", f"The download failed:\n{err}")
        else:
            QMessageBox.information(parent, "Speech model", "Speech recognition is ready.")
    th.progress.connect(prog)
    th.done.connect(finished)
    dlg.canceled.connect(th.terminate)
    th.start()
    parent._model_thread = th  # keep a reference


class SettingsDialog(QDialog):
    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.setWindowTitle("Settings")
        lay = QVBoxLayout(self)

        ap = QGroupBox("Appearance")
        af = QFormLayout(ap)
        self.theme = QComboBox()
        self.theme.addItems(list(THEMES))
        self.theme.setCurrentText(ctx.get("ui/theme", "light"))
        af.addRow("Theme", self.theme)
        self.scale = QDoubleSpinBox()
        self.scale.setRange(0.8, 2.5)
        self.scale.setSingleStep(0.1)
        self.scale.setValue(ctx.get("ui/font_scale", 1.0, float))
        af.addRow("Text size", self.scale)
        lay.addWidget(ap)

        vo = QGroupBox("Reading voice")
        vf = QFormLayout(vo)
        self.engine = QComboBox()
        for eid, desc in engines():
            self.engine.addItem(desc, eid)
        self.engine.setCurrentIndex(max(0, self.engine.findData(ctx.get("voice/engine", "") or ctx.speaker.engine)))
        self.engine.currentIndexChanged.connect(self._fill_voices)
        vf.addRow("Engine", self.engine)
        vrow = QHBoxLayout()
        self.voice = QComboBox()
        vrow.addWidget(self.voice, 1)
        self.get_voices = QPushButton("Get natural voices…")
        self.get_voices.setToolTip("Download neural Piper voices: much more natural, still fully offline")
        self.get_voices.clicked.connect(self._download_piper)
        self.get_voices.setEnabled(piper_available())
        vrow.addWidget(self.get_voices)
        vf.addRow("Voice", vrow)
        self._fill_voices()
        srow = QHBoxLayout()
        self.speaker_dev = QComboBox()
        srow.addWidget(self.speaker_dev, 1)
        refresh = QPushButton("Refresh devices")
        refresh.setToolTip("Look for newly connected microphones and speakers")
        refresh.clicked.connect(self._refresh_devices)
        srow.addWidget(refresh)
        vf.addRow("Speaker", srow)
        note = QLabel("Speaker choice applies to natural (Piper) and classic Windows voices. Modern Windows "
                      "voices always play on the system default speaker.")
        note.setWordWrap(True)
        note.setObjectName("muted")
        vf.addRow(note)
        self.rate = QSlider(Qt.Horizontal)
        self.rate.setRange(-10, 10)
        self.rate.setValue(int(ctx.get("voice/rate", 0.0, float) * 10))
        vf.addRow("Reading speed", self.rate)
        self.pitch = QSlider(Qt.Horizontal)
        self.pitch.setRange(-10, 10)
        self.pitch.setValue(int(ctx.get("voice/pitch", 0.0, float) * 10))
        vf.addRow("Pitch", self.pitch)
        self.volume = QSlider(Qt.Horizontal)
        self.volume.setRange(0, 10)
        self.volume.setValue(int(ctx.get("voice/volume", 1.0, float) * 10))
        vf.addRow("Volume", self.volume)
        test = QPushButton("Test voice")
        test.clicked.connect(self._test)
        vf.addRow(test)
        lay.addWidget(vo)

        li = QGroupBox("Listening")
        vf = QFormLayout(li)
        self.mic = QComboBox()
        vf.addRow("Microphone", self.mic)
        self._fill_devices()
        self.nr = QCheckBox("Background noise reduction")
        self.nr.setToolTip("Learns the steady background sound (fans, hum, hiss) and removes it. Helps in noisy "
                           "rooms; in a quiet room it can slightly reduce accuracy, so it's off by default.")
        self.nr.setChecked(ctx.get("audio/noise_reduction", False, bool))
        self.gate = QCheckBox("Noise gate (silence between words)")
        self.gate.setToolTip("Mutes the microphone when you're not speaking. Always used for saved recordings; "
                             "for recognition it can clip very quiet words, so it's off by default.")
        self.gate.setChecked(ctx.get("audio/gate", False, bool))
        self.comp = QCheckBox("Compressor (evens out loud and quiet speech)")
        self.comp.setToolTip("Brings soft speech up and keeps loud speech from distorting. Recommended.")
        self.comp.setChecked(ctx.get("audio/compressor", True, bool))
        proc = QHBoxLayout()
        for w in (self.nr, self.gate, self.comp):
            proc.addWidget(w)
        vf.addRow("Mic processing", proc)
        self.record = QComboBox()
        for k, label in audio.RECORD_FORMATS.items():
            self.record.addItem(label, k)
        self.record.setCurrentIndex(max(0, self.record.findData(ctx.get("audio/record_format", "") or "")))
        self.record.setToolTip("Recordings are saved in the project's 'audio' folder, one file per listening "
                               "session. The text transcript is always kept.")
        vf.addRow("Save audio", self.record)
        self.silence = QSpinBox()
        self.silence.setRange(3, 60)
        self.silence.setSuffix(" seconds")
        self.silence.setValue(ctx.get("voice/silence_seconds", 10, int))
        vf.addRow("Pause after silence of", self.silence)
        self.narr_default = QCheckBox("Start interviews in Narration mode")
        self.narr_default.setChecked(ctx.get("voice/narration_default", False, bool))
        vf.addRow(self.narr_default)
        mrow = QHBoxLayout()
        self.stt_model = QComboBox()
        self.stt_model.addItem("(automatic)", "")
        for m in installed_models():
            self.stt_model.addItem(m, m)
        self.stt_model.setCurrentIndex(max(0, self.stt_model.findData(ctx.get("voice/stt_model", "") or "")))
        self.stt_model.setToolTip("Choose a model for another language by installing it first (see README)")
        mrow.addWidget(self.stt_model, 1)
        dl = QPushButton("Download model…")
        dl.clicked.connect(lambda: download_model(self, ctx))
        mrow.addWidget(dl)
        vf.addRow("Speech model / language", mrow)
        st = stt_status()
        lab = QLabel("Speech recognition: " + ("ready" if not st else st))
        lab.setWordWrap(True)
        lab.setObjectName("muted")
        vf.addRow(lab)
        nrow = QHBoxLayout()
        nlab = QLabel("Name lists for spelling checks: " +
                      ("installed" if names_mod.name_lists_installed() else "built-in basics only"))
        nlab.setObjectName("muted")
        nrow.addWidget(nlab, 1)
        ssa = QPushButton("Import SSA names.zip…")
        ssa.setToolTip("Use the official, larger US first-name list downloaded from ssa.gov")
        ssa.clicked.connect(self._import_ssa)
        nrow.addWidget(ssa)
        vf.addRow(nrow)
        ai = QPushButton("Local AI assistant (optional)…")
        ai.setToolTip("Optional small local model for freer Talk-mode phrasing. Runs offline; never writes.")
        ai.clicked.connect(self._open_ai)
        vf.addRow(ai)
        lay.addWidget(li)

        bk = QGroupBox("Backups")
        bf = QFormLayout(bk)
        self.keep_all = QCheckBox("Keep every snapshot (recommended — they're small)")
        self.keep_all.setChecked(ctx.get("backup/keep_all", True, bool))
        bf.addRow(self.keep_all)
        self.max = QSpinBox()
        self.max.setRange(10, 5000)
        self.max.setValue(ctx.get("backup/max", 200, int))
        bf.addRow("Otherwise keep the newest", self.max)
        self.interval = QSpinBox()
        self.interval.setRange(1, 120)
        self.interval.setSuffix(" minutes")
        self.interval.setValue(ctx.get("backup/interval_min", 5, int))
        bf.addRow("Snapshot while working every", self.interval)
        lay.addWidget(bk)

        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self._save)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def _fill_devices(self) -> None:
        for combo, kind in ((self.mic, "input"), (self.speaker_dev, "output")):
            current = self.ctx.device_setting(kind) if combo.count() == 0 else (combo.currentData() or "")
            combo.clear()
            combo.addItem(audio.describe_setting(audio.COMM, kind) + "  (recommended)", audio.COMM)
            combo.addItem("System default device", audio.SYSTEM)
            for _, name in audio.list_devices(kind):
                combo.addItem(name, name)
            i = combo.findData(current)
            if i < 0 and current:
                combo.addItem(f"{current}  (not connected)", current)
                i = combo.count() - 1
            combo.setCurrentIndex(max(0, i))

    def _refresh_devices(self) -> None:
        if self.ctx.listener.listening:
            QMessageBox.information(self, "Devices", "Stop listening first, then refresh.")
            return
        audio.rescan_devices()
        self._fill_devices()

    def _open_ai(self) -> None:
        from .ai_dialog import LocalAIDialog
        LocalAIDialog(self.ctx, self).exec()
        self.ctx.set("ai/offered", True)

    def _fill_voices(self) -> None:
        eng = self.engine.currentData() or ""
        self.voice.clear()
        self.voice.addItem("(default)", "")
        for v in self.ctx.speaker.voices(eng):
            label = f"{v}  —  {PIPER_VOICES[v]}" if eng == "piper" and v in PIPER_VOICES else v
            self.voice.addItem(label, v)
        self.voice.setCurrentIndex(max(0, self.voice.findData(self.ctx.get("voice/name", ""))))
        if eng == "piper" and self.voice.count() == 1:
            self.voice.setItemText(0, "(no natural voices yet — click Get natural voices…)")

    def _download_piper(self) -> None:
        from PySide6.QtWidgets import QInputDialog
        have = set(piper_installed())
        keys = list(PIPER_VOICES)
        labels = [f"{k}  —  {PIPER_VOICES[k]}" + ("  (installed)" if k in have else "") for k in keys]
        choice, ok = QInputDialog.getItem(self, "Natural voices",
                                          "Each voice is about 60–110 MB, downloaded once from the public\n"
                                          "Rhasspy Piper voice library. The training data for each voice is\n"
                                          "shown; the first three were trained only on public-domain or\n"
                                          "donated recordings. Which voice?", labels, 0, False)
        if not ok:
            return
        voice = keys[labels.index(choice)]
        dlg = QProgressDialog(f"Downloading {voice}…", "Cancel", 0, 100, self)
        dlg.setMinimumDuration(0)
        dlg.setAutoClose(False)
        th = PiperDownloader(voice, self)
        th.progress.connect(lambda d, t: t and dlg.setValue(int(d * 100 / t)))

        def finished(err):
            dlg.close()
            if err:
                QMessageBox.warning(self, "Natural voices", f"The download failed:\n{err}")
                return
            i = self.engine.findData("piper")
            if i >= 0:
                self.engine.setCurrentIndex(i)
            self._fill_voices()
            self.voice.setCurrentIndex(max(0, self.voice.findData(voice)))
        th.done.connect(finished)
        dlg.canceled.connect(th.terminate)
        th.start()
        self._piper_thread = th

    def _import_ssa(self) -> None:
        from PySide6.QtWidgets import QFileDialog
        f, _ = QFileDialog.getOpenFileName(self, "Import SSA baby names (names.zip from ssa.gov)", "",
                                           "SSA names (*.zip)")
        if not f:
            return
        try:
            n = names_mod.import_ssa_zip(f)
            QMessageBox.information(self, "Name lists", f"Imported {n:,} first names.")
        except Exception as e:
            QMessageBox.warning(self, "Name lists", str(e))

    def _test(self) -> None:
        sp = self.speaker_dev.currentData() or ""
        self.ctx.speaker.apply_settings(self.rate.value() / 10, self.volume.value() / 10,
                                        self.voice.currentData() or "", engine=self.engine.currentData() or "",
                                        pitch=self.pitch.value() / 10,
                                        output_device=None if sp == audio.SYSTEM else
                                        audio.resolve_device(sp, "output"))
        self.ctx.speaker.say("Hello. This is how your interview questions will sound. "
                             "Tell me about your main character.")

    def _save(self) -> None:
        c = self.ctx
        c.set("ui/theme", self.theme.currentText())
        c.set("ui/font_scale", self.scale.value())
        c.set("voice/engine", self.engine.currentData() or "")
        c.set("voice/name", self.voice.currentData() or "")
        c.set("voice/pitch", self.pitch.value() / 10)
        c.set("voice/stt_model", self.stt_model.currentData() or "")
        c.set("voice/rate", self.rate.value() / 10)
        c.set("voice/volume", self.volume.value() / 10)
        c.set("voice/input_device", self.mic.currentData() or "")
        c.set("voice/output_device", self.speaker_dev.currentData() or "")
        c.set("audio/noise_reduction", self.nr.isChecked())
        c.set("audio/gate", self.gate.isChecked())
        c.set("audio/compressor", self.comp.isChecked())
        c.set("audio/record_format", self.record.currentData() or "")
        c.set("voice/silence_seconds", self.silence.value())
        c.set("voice/narration_default", self.narr_default.isChecked())
        c.set("backup/keep_all", self.keep_all.isChecked())
        c.set("backup/max", self.max.value())
        c.set("backup/interval_min", self.interval.value())
        c.apply_voice_settings()
        if c.backups:
            c.backups.keep_all = self.keep_all.isChecked()
            c.backups.max_snapshots = self.max.value()
        self.accept()
