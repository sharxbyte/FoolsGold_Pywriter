"""Shared widgets and helpers."""
from __future__ import annotations

import html
import re

from PySide6.QtCore import QPoint, Qt, QUrl, Signal
from PySide6.QtGui import QGuiApplication, QTextCursor
from PySide6.QtWidgets import (QApplication, QLabel, QPlainTextEdit, QProgressBar, QPushButton, QTextBrowser,
                               QToolTip, QWidget)

from ..summary import tooltip_html
from ..voice import parse_command, tidy_dictation

KIND_COLORS = {
    "character": "#c0504d", "location": "#4f81bd", "group": "#8064a2", "item": "#f79646",
    "event": "#4bacc6", "plot": "#9bbb59", "theme": "#7f7f7f", "topic": "#9bbb59",
    "source": "#948a54", "scene": "#666666", "project": "#333333",
}


def center_on_screen(w: QWidget, frac_w: float = 0.5, frac_h: float = 0.5, resize: bool = True) -> None:
    """Size a window to a fraction of its screen and center it."""
    screen = w.screen() if w.screen() else QGuiApplication.primaryScreen()
    if screen is None:
        return
    geo = screen.availableGeometry()
    if resize:
        w.resize(int(geo.width() * frac_w), int(geo.height() * frac_h))
    fg = w.frameGeometry()
    fg.moveCenter(geo.center())
    w.move(fg.topLeft())


def linkify(store, text: str, exclude: str | None = None) -> str:
    """HTML-escape text and turn mentions of known entities into entity:// links."""
    if not text:
        return ""
    names = [(eid, n) for eid, _, n in store.all_names() if eid != exclude and len(n) >= 3]
    names.sort(key=lambda r: -len(r[1]))
    esc = html.escape(text)
    if not names:
        return esc.replace("\n", "<br>")
    lookup = {}
    parts = []
    for eid, n in names:
        lookup[n.lower()] = eid
        parts.append(re.escape(html.escape(n)))
    pat = re.compile(r"\b(" + "|".join(parts) + r")\b", re.I)

    def sub(m):
        eid = lookup.get(html.unescape(m.group(1)).lower())
        return f"<a href='entity://{eid}'>{m.group(1)}</a>" if eid else m.group(1)
    return pat.sub(sub, esc).replace("\n", "<br>")


class EntityBrowser(QTextBrowser):
    """Read-only rich text where entity links show a condensed bio on hover and
    open the full sheet on click."""

    entity_clicked = Signal(str)

    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.setOpenLinks(False)
        self.setMouseTracking(True)
        self.anchorClicked.connect(self._on_anchor)
        self._last_anchor = ""

    def _on_anchor(self, url: QUrl) -> None:
        if url.scheme() == "entity":
            self.entity_clicked.emit(url.host().upper() or url.path().strip("/").upper())

    def mouseMoveEvent(self, e):
        super().mouseMoveEvent(e)
        anchor = self.anchorAt(e.position().toPoint())
        if anchor.startswith("entity://"):
            if anchor != self._last_anchor and self.ctx.store:
                self._last_anchor = anchor
                eid = anchor[len("entity://"):].strip("/").upper()
                QToolTip.showText(e.globalPosition().toPoint() + QPoint(12, 12),
                                  tooltip_html(self.ctx.store, eid), self)
        else:
            if self._last_anchor:
                QToolTip.hideText()
            self._last_anchor = ""


class LinkLabel(QLabel):
    """A single clickable entity chip with a hover bio."""

    clicked = Signal(str)

    def __init__(self, ctx, entity_id: str, text: str, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.entity_id = entity_id
        e = ctx.store.get(entity_id, with_fields=False)
        color = KIND_COLORS.get(e.kind if e else "", "#666")
        self.setText(f"<a href='#' style='color:{color};text-decoration:none'>{html.escape(text)}</a>")
        self.setTextInteractionFlags(Qt.TextBrowserInteraction)
        self.linkActivated.connect(lambda _: self.clicked.emit(self.entity_id))
        self.setCursor(Qt.PointingHandCursor)

    def enterEvent(self, e):
        QToolTip.showText(self.mapToGlobal(QPoint(0, self.height())),
                          tooltip_html(self.ctx.store, self.entity_id), self)
        super().enterEvent(e)


class DictationTarget:
    """Glue that sends recognized speech into a text widget (QPlainTextEdit/QLineEdit)."""

    def __init__(self, widget, names: list[str] | None = None):
        self.widget = widget
        self.names = names

    def insert(self, text: str) -> None:
        if self.names is None:
            ctx = getattr(QApplication.instance(), "pywriter_ctx", None)
            self.names = [n for _, _, n in ctx.store.all_names()] if ctx and ctx.store else []
        text = tidy_dictation(text, self.names)
        w = self.widget
        if isinstance(w, QPlainTextEdit):
            cur = w.textCursor()
            before = w.toPlainText()[:cur.position()]
            if before and not before.endswith((" ", "\n")):
                text = " " + text
            cur.insertText(text)
            w.setTextCursor(cur)
            w.ensureCursorVisible()
        elif hasattr(w, "insert"):
            existing = w.text()
            w.insert((" " if existing and not existing.endswith(" ") else "") + text.rstrip("."))


class LevelMeter(QProgressBar):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setRange(0, 100)
        self.setTextVisible(False)
        self.setFixedHeight(8)
        self.setMaximumWidth(120)

    def set_level(self, v: float) -> None:
        self.setValue(int(v * 100))


def busy(on: bool) -> None:
    if on:
        QApplication.setOverrideCursor(Qt.WaitCursor)
    else:
        QApplication.restoreOverrideCursor()
