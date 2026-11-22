"""Local AI assistant: explanation, download, enable/disable and delete."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QDialog, QHBoxLayout, QLabel, QMessageBox,
                               QProgressBar, QPushButton, QRadioButton, QTextBrowser, QVBoxLayout)

from ..llm import ABOUT_HTML, MODELS, LLMDownloader, delete_model, installed_models, model_path, runtime_available
from .common import center_on_screen


class LocalAIDialog(QDialog):
    def __init__(self, ctx, parent=None, first_run: bool = False):
        super().__init__(parent)
        self.ctx = ctx
        self.setWindowTitle("Local AI assistant (optional)")
        lay = QVBoxLayout(self)
        if first_run:
            intro = QLabel("<b>Welcome!</b> Before you start, there's one optional add-on you might like. "
                           "You can skip it now and add it any time from <b>Tools ▸ Local AI assistant…</b>")
            intro.setWordWrap(True)
            lay.addWidget(intro)
        about = QTextBrowser()
        about.setOpenExternalLinks(True)
        about.setHtml(ABOUT_HTML)
        lay.addWidget(about, 1)

        lay.addWidget(QLabel("<b>Choose a model:</b>"))
        self.group = QButtonGroup(self)
        current = ctx.get("ai/model", "") or "qwen2.5-1.5b"
        for mid, info in MODELS.items():
            rb = QRadioButton(f"{info.title}  —  {info.file_mb / 1000:.1f} GB download, about {info.ram_gb:g} GB "
                              f"of memory while running. {info.note}")
            rb.setProperty("mid", mid)
            rb.setChecked(mid == current)
            rb.toggled.connect(self._refresh)
            self.group.addButton(rb)
            lay.addWidget(rb)
            if info.page:
                link = QLabel(f"&nbsp;&nbsp;&nbsp;&nbsp;Source: <a href='{info.page}'>{info.page}</a>")
                link.setOpenExternalLinks(True)
                link.setObjectName("muted")
                lay.addWidget(link)

        self.enable = QCheckBox("Use the local AI assistant in Talk mode")
        self.enable.setChecked(ctx.get("ai/enabled", False, bool))
        self.enable.toggled.connect(self._toggle_enabled)
        lay.addWidget(self.enable)
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setObjectName("muted")
        lay.addWidget(self.status)
        self.progress = QProgressBar()
        self.progress.setVisible(False)
        lay.addWidget(self.progress)

        row = QHBoxLayout()
        self.download_btn = QPushButton("Download model")
        self.download_btn.setObjectName("primary")
        self.download_btn.clicked.connect(self._download)
        row.addWidget(self.download_btn)
        self.cancel_btn = QPushButton("Cancel download")
        self.cancel_btn.clicked.connect(self._cancel)
        self.cancel_btn.setVisible(False)
        row.addWidget(self.cancel_btn)
        self.delete_btn = QPushButton("Delete model")
        self.delete_btn.clicked.connect(self._delete)
        row.addWidget(self.delete_btn)
        row.addStretch(1)
        close = QPushButton("Not now" if first_run else "Close")
        close.clicked.connect(self.accept)
        row.addWidget(close)
        lay.addLayout(row)
        self._thread: LLMDownloader | None = None
        self._refresh()
        center_on_screen(self, 0.5, 0.75)

    def _mid(self) -> str:
        b = self.group.checkedButton()
        return b.property("mid") if b else "qwen2.5-1.5b"

    def _refresh(self) -> None:
        mid = self._mid()
        have = mid in installed_models()
        rt = runtime_available()
        self.download_btn.setVisible(not have and self._thread is None)
        self.delete_btn.setEnabled(have and self._thread is None)
        self.enable.setEnabled(have and rt)
        if not rt:
            self.status.setText("The llama-cpp-python package isn't installed, so the assistant can't run. "
                                "Install it with:  pip install llama-cpp-python  (see README).")
        elif not have:
            part = model_path(mid).with_suffix(".part")
            if part.exists():
                self.status.setText(f"{MODELS[mid].title}: a partial download "
                                    f"({part.stat().st_size // 1_000_000} MB) is waiting. "
                                    f"Click Download to resume.")
                self.download_btn.setText("Resume download")
            else:
                self.status.setText(f"{MODELS[mid].title} isn't downloaded yet. Click Download to fetch it "
                                    f"({MODELS[mid].file_mb / 1000:.1f} GB) and install it automatically.")
                self.download_btn.setText("Download and install")
        else:
            state = "loaded and ready" if self.ctx.assistant.ready and self.ctx.assistant.model_id == mid else \
                "downloaded (it loads in the background when enabled)"
            on = "ON" if self.enable.isChecked() else "OFF"
            self.status.setText(f"{MODELS[mid].title}: {state}. Assistant is {on}.  File: {model_path(mid)}")

    def _apply(self) -> None:
        self.ctx.set("ai/model", self._mid())
        self.ctx.set("ai/enabled", self.enable.isChecked() and self._mid() in installed_models())
        self.ctx.apply_voice_settings()

    def _toggle_enabled(self, on: bool) -> None:
        self._apply()
        self._refresh()

    def _download(self) -> None:
        mid = self._mid()
        self._thread = LLMDownloader(mid, self)
        self.progress.setVisible(True)
        self.progress.setValue(0)
        self.cancel_btn.setVisible(True)
        self.download_btn.setVisible(False)
        self._thread.progress.connect(lambda d, t: t and (self.progress.setValue(int(d * 100 / t)),
                                                          self.progress.setFormat(f"{d // 1_000_000} of "
                                                                                  f"{t // 1_000_000} MB")))
        self._thread.done.connect(self._downloaded)
        self._thread.start()

    def _cancel(self) -> None:
        if self._thread:
            self._thread.cancel()

    def _downloaded(self, err: str) -> None:
        self._thread = None
        self.progress.setVisible(False)
        self.cancel_btn.setVisible(False)
        if err and err != "cancelled":
            QMessageBox.warning(self, "Download failed", err)
        elif not err:
            self.enable.setChecked(True)   # downloading is opting in; untick to switch off
            self._apply()
        self._refresh()

    def _delete(self) -> None:
        mid = self._mid()
        if QMessageBox.question(self, "Delete model", f"Delete {MODELS[mid].title} and free "
                                f"{MODELS[mid].file_mb / 1000:.1f} GB? You can download it again later.") \
                != QMessageBox.Yes:
            return
        if self.ctx.assistant.model_id == mid:
            self.ctx.assistant.unload()
        delete_model(mid)
        self.enable.setChecked(False)
        self._apply()
        self._refresh()

    def closeEvent(self, e) -> None:
        if self._thread:
            self._thread.cancel()
            self._thread.wait(3000)
        super().closeEvent(e)
