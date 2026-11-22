"""Start screen: create a project (validated title -> project folder) or open one."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QValidator
from PySide6.QtWidgets import (QButtonGroup, QDialog, QFileDialog, QFrame, QHBoxLayout, QLabel, QLineEdit,
                               QListWidget, QListWidgetItem, QMessageBox, QPushButton, QRadioButton,
                               QVBoxLayout, QWidget)

from .. import APP_DISPLAY_NAME
from ..paths import default_projects_dir, validate_folder_name
from ..store import ProjectStore
from .common import center_on_screen

PROJECT_TYPES = [
    ("Fiction", "Novels, short stories and invented worlds"),
    ("Biography", "A real person's life, including your own"),
    ("Non-Fiction", "Ideas, history, how-to and research"),
]


class TitleValidator(QValidator):
    """Blocks characters that can't be used in a folder name as they're typed."""

    def validate(self, text: str, pos: int):
        if any(c in '<>:"/\\|?*' or ord(c) < 32 for c in text):
            return QValidator.Invalid, text, pos
        return QValidator.Acceptable if text.strip() else QValidator.Intermediate, text, pos


class ProjectDialog(QDialog):
    def __init__(self, ctx, parent=None, allow_cancel: bool = True):
        super().__init__(parent)
        self.ctx = ctx
        self.result_store: ProjectStore | None = None
        self.setWindowTitle(APP_DISPLAY_NAME)
        lay = QHBoxLayout(self)

        # ---- new project
        new = QFrame()
        nl = QVBoxLayout(new)
        h = QLabel("Start a new project")
        h.setObjectName("h1")
        nl.addWidget(h)
        nl.addWidget(QLabel("What kind of project is it?"))
        self.type_group = QButtonGroup(self)
        for i, (name, desc) in enumerate(PROJECT_TYPES):
            rb = QRadioButton(f"{name}  —  {desc}")
            rb.setProperty("ptype", name)
            self.type_group.addButton(rb, i)
            nl.addWidget(rb)
            if i == 0:
                rb.setChecked(True)
        nl.addSpacing(10)
        nl.addWidget(QLabel("What is the working title? (This also names the project folder.)"))
        self.title = QLineEdit()
        self.title.setPlaceholderText("e.g. The Salt Road")
        self.title.setValidator(TitleValidator(self))
        self.title.textChanged.connect(self._validate)
        self.title.returnPressed.connect(self._create)
        nl.addWidget(self.title)
        self.msg = QLabel(" ")
        self.msg.setObjectName("muted")
        self.msg.setWordWrap(True)
        nl.addWidget(self.msg)
        loc_row = QHBoxLayout()
        self.folder_label = QLabel()
        self.folder_label.setObjectName("muted")
        self.folder_label.setWordWrap(True)
        loc_row.addWidget(self.folder_label, 1)
        change = QPushButton("Change location…")
        change.clicked.connect(self._pick_base)
        loc_row.addWidget(change)
        nl.addLayout(loc_row)
        self.base_dir = Path(ctx.get("projects_dir", str(default_projects_dir())))
        self.create_btn = QPushButton("Create project")
        self.create_btn.setObjectName("primary")
        self.create_btn.clicked.connect(self._create)
        nl.addStretch(1)
        nl.addWidget(self.create_btn)
        lay.addWidget(new, 3)

        # ---- open project
        op = QWidget()
        ol = QVBoxLayout(op)
        h2 = QLabel("Open a project")
        h2.setObjectName("h1")
        ol.addWidget(h2)
        self.recent = QListWidget()
        for p in ctx.recent_projects():
            if Path(p).exists():
                it = QListWidgetItem(f"{Path(p).stem}\n{Path(p).parent}")
                it.setData(Qt.UserRole, p)
                self.recent.addItem(it)
        self.recent.itemActivated.connect(lambda it: self._open(Path(it.data(Qt.UserRole))))
        ol.addWidget(QLabel("Recent projects (double-click to open):"))
        ol.addWidget(self.recent, 1)
        btns = QHBoxLayout()
        b = QPushButton("Open selected")
        b.clicked.connect(lambda: self.recent.currentItem() and
                          self._open(Path(self.recent.currentItem().data(Qt.UserRole))))
        btns.addWidget(b)
        b2 = QPushButton("Browse…")
        b2.clicked.connect(self._browse)
        btns.addWidget(b2)
        ol.addLayout(btns)
        if allow_cancel:
            c = QPushButton("Cancel")
            c.clicked.connect(self.reject)
            ol.addWidget(c)
        lay.addWidget(op, 2)
        self._validate()
        center_on_screen(self, 0.55, 0.5)
        self.title.setFocus()

    def _ptype(self) -> str:
        return self.type_group.checkedButton().property("ptype")

    def _validate(self) -> bool:
        title = self.title.text()
        err = validate_folder_name(title) if title else None
        target = self.base_dir / title.strip() if title.strip() else self.base_dir / "<title>"
        self.folder_label.setText(f"Project folder: {target}")
        if err:
            self.msg.setText(f"⚠ {err}")
        elif title and (self.base_dir / title).exists():
            self.msg.setText("⚠ A folder with this name already exists. Choose another title or location.")
            err = "exists"
        else:
            self.msg.setText(" ")
        ok = bool(title) and not err
        self.create_btn.setEnabled(ok)
        return ok

    def _pick_base(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "Where should projects be stored?", str(self.base_dir))
        if d:
            self.base_dir = Path(d)
            self.ctx.set("projects_dir", d)
            self._validate()

    def _create(self) -> None:
        if not self._validate():
            return
        title = self.title.text()
        folder = self.base_dir / title
        try:
            self.result_store = ProjectStore.create(folder, title, self._ptype())
        except OSError as e:
            QMessageBox.warning(self, "Couldn't create project", str(e))
            return
        self.accept()

    def _browse(self) -> None:
        f, _ = QFileDialog.getOpenFileName(self, "Open project", str(self.base_dir),
                                           f"PyWriter project (*{ProjectStore.EXT})")
        if f:
            self._open(Path(f))

    def _open(self, path: Path) -> None:
        if not path.exists():
            QMessageBox.warning(self, "Not found", f"{path} no longer exists.")
            return
        try:
            self.result_store = ProjectStore(path)
        except Exception as e:
            QMessageBox.warning(self, "Couldn't open project", str(e))
            return
        self.accept()
