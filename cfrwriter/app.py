"""Application entry point."""

from __future__ import annotations

import sys

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from . import APP_NAME, assets
from .settings import load_settings
from .ui.main_window import MainWindow


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName(APP_NAME)
    family = assets.load_fonts()
    window = MainWindow(load_settings(), family)
    window.show()
    QTimer.singleShot(0, window.maybe_first_run)
    code = app.exec()
    # Destroy the window while the QApplication still exists. Left to Python's normal cleanup,
    # `app` is released first and the window is torn down afterwards, which crashes at exit.
    window.deleteLater()
    app.processEvents()
    del window
    return code


if __name__ == "__main__":
    sys.exit(main())
