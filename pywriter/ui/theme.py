"""Light and dark themes (Fusion style + palette + a small stylesheet)."""
from __future__ import annotations

from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import QApplication

THEMES = {
    "light": {
        "window": "#f6f1e7", "base": "#fffdf8", "alt": "#f0e9da", "text": "#2b2620", "muted": "#7a6f60",
        "button": "#ece3d2", "highlight": "#b5651d", "htext": "#ffffff", "border": "#d8ccb6",
        "accent": "#b5651d", "link": "#9a4f10",
    },
    "dark": {
        "window": "#1f2124", "base": "#26292d", "alt": "#2d3136", "text": "#e6e1d8", "muted": "#9b968c",
        "button": "#33373c", "highlight": "#d08a3c", "htext": "#111111", "border": "#3d4248",
        "accent": "#d08a3c", "link": "#e3a25a",
    },
    "high contrast": {
        "window": "#000000", "base": "#000000", "alt": "#111111", "text": "#ffffff", "muted": "#dddddd",
        "button": "#000000", "highlight": "#ffff00", "htext": "#000000", "border": "#ffffff",
        "accent": "#ffff00", "link": "#00ffff",
    },
}


def apply_theme(app: QApplication, name: str = "light", font_scale: float = 1.0) -> dict:
    t = THEMES.get(name, THEMES["light"])
    app.setStyle("Fusion")
    p = QPalette()
    c = lambda k: QColor(t[k])  # noqa: E731
    p.setColor(QPalette.Window, c("window"))
    p.setColor(QPalette.WindowText, c("text"))
    p.setColor(QPalette.Base, c("base"))
    p.setColor(QPalette.AlternateBase, c("alt"))
    p.setColor(QPalette.Text, c("text"))
    p.setColor(QPalette.Button, c("button"))
    p.setColor(QPalette.ButtonText, c("text"))
    p.setColor(QPalette.Highlight, c("highlight"))
    p.setColor(QPalette.HighlightedText, c("htext"))
    p.setColor(QPalette.ToolTipBase, c("base"))
    p.setColor(QPalette.ToolTipText, c("text"))
    p.setColor(QPalette.Link, c("link"))
    p.setColor(QPalette.PlaceholderText, c("muted"))
    p.setColor(QPalette.Disabled, QPalette.Text, c("muted"))
    p.setColor(QPalette.Disabled, QPalette.ButtonText, c("muted"))
    app.setPalette(p)
    f = QFont(app.font())
    base = 10.5
    f.setPointSizeF(base * font_scale)
    app.setFont(f)
    app.setStyleSheet(f"""
        QToolTip {{ background: {t['base']}; color: {t['text']}; border: 1px solid {t['border']}; padding: 6px; }}
        QPushButton {{ padding: 5px 12px; border: 1px solid {t['border']}; border-radius: 5px; background: {t['button']}; }}
        QPushButton:hover {{ border-color: {t['accent']}; }}
        QPushButton:checked {{ background: {t['accent']}; color: {t['htext']}; }}
        QPushButton#primary {{ background: {t['accent']}; color: {t['htext']}; font-weight: bold; }}
        QLineEdit, QPlainTextEdit, QTextEdit, QTextBrowser, QComboBox, QSpinBox, QListWidget, QTreeWidget, QTreeView {{
            border: 1px solid {t['border']}; border-radius: 4px; }}
        QLabel#question {{ font-size: {int(17 * font_scale)}pt; }}
        QLabel#section {{ color: {t['accent']}; font-weight: bold; letter-spacing: 1px; }}
        QLabel#muted {{ color: {t['muted']}; }}
        QLabel#h1 {{ font-size: {int(18 * font_scale)}pt; font-weight: bold; }}
        QLabel#h2 {{ font-size: {int(12.5 * font_scale)}pt; font-weight: bold; color: {t['accent']}; }}
        QListWidget#nav {{ border: none; background: {t['alt']}; font-size: {int(11.5 * font_scale)}pt; }}
        QListWidget#nav::item {{ padding: 8px 10px; }}
        QListWidget#nav::item:selected {{ background: {t['accent']}; color: {t['htext']}; }}
        QTabBar::tab {{ padding: 6px 14px; }}
        QGroupBox {{ font-weight: bold; border: 1px solid {t['border']}; border-radius: 6px; margin-top: 12px; padding-top: 8px; }}
        QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 4px; color: {t['accent']}; }}
    """)
    return t
