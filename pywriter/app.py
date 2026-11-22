"""Application entry point."""
from __future__ import annotations

import sys
import traceback
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import QApplication, QMessageBox, QSplashScreen

from . import APP_DISPLAY_NAME, APP_NAME
from .paths import resource_dir, user_data_dir


def _excepthook(etype, value, tb):
    text = "".join(traceback.format_exception(etype, value, tb))
    try:
        (user_data_dir() / "error.log").open("a", encoding="utf-8").write(text + "\n")
    except Exception:
        pass
    sys.__stderr__.write(text)
    if QApplication.instance():
        QMessageBox.warning(None, APP_DISPLAY_NAME,
                            f"Something went wrong, but your work is saved.\n\n{value}\n\n"
                            f"Details were written to {user_data_dir() / 'error.log'}")


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv
    sys.excepthook = _excepthook
    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_DISPLAY_NAME)
    icon = resource_dir() / "resources" / "Icon.ico"
    if icon.exists():
        app.setWindowIcon(QIcon(str(icon)))

    from .ui.context import AppContext
    from .ui.theme import apply_theme
    ctx = AppContext()
    app.pywriter_ctx = ctx
    apply_theme(app, ctx.get("ui/theme", "light"), ctx.get("ui/font_scale", 1.0, float))

    splash = None
    sp = resource_dir() / "resources" / "splash.png"
    if sp.exists() and "--no-splash" not in argv:
        pm = QPixmap(str(sp))
        screen = app.primaryScreen().availableGeometry()
        pm = pm.scaled(int(screen.width() * 0.4), int(screen.height() * 0.4), Qt.KeepAspectRatio,
                       Qt.SmoothTransformation)
        splash = QSplashScreen(pm)
        splash.show()
        app.processEvents()

    if ctx.library.errors:
        QMessageBox.warning(None, APP_DISPLAY_NAME, "Some question packs couldn't be loaded:\n\n" +
                            "\n".join(ctx.library.errors))

    from .store import ProjectStore
    from .ui.main_window import MainWindow
    from .ui.project_dialog import ProjectDialog

    store = None
    # a project path on the command line, or the last project
    args = [a for a in argv[1:] if not a.startswith("--")]
    candidate = Path(args[0]) if args else (Path(ctx.get("last_project", "")) if ctx.get("last_project") else None)
    if candidate and candidate.suffix == ProjectStore.EXT and candidate.exists():
        try:
            store = ProjectStore(candidate)
        except Exception:
            store = None
    new_project = False
    if store is None:
        if splash:
            splash.close()
            splash = None
        dlg = ProjectDialog(ctx, allow_cancel=False)
        if not dlg.exec() or not dlg.result_store:
            return 0
        store = dlg.result_store
        new_project = store.revision_count() <= 4
    ctx.attach(store)
    win = MainWindow(ctx)
    win.show()
    if splash:
        QTimer.singleShot(900, lambda: splash.finish(win))
    if "--no-guide" not in argv:
        QTimer.singleShot(400, lambda: win.first_run_offers(new_project))
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
