"""Punto de entrada de la aplicación gráfica."""

from __future__ import annotations

import sys
import traceback

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QMessageBox

from linux_optimizer import APP_NAME, __version__
from linux_optimizer.main_window import MainWindow
from linux_optimizer.resources import ICON_PATH
from linux_optimizer.theme import THEME_QSS


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv if argv is None else argv)
    app = QApplication(argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(__version__)
    app.setOrganizationName("LinuxOptimizer")
    app.setStyle("Fusion")
    app.setStyleSheet(THEME_QSS)
    app.setWindowIcon(QIcon(str(ICON_PATH)))

    try:
        window = MainWindow()
    except Exception:
        traceback.print_exc()
        QMessageBox.critical(
            None,
            APP_NAME,
            "Error al iniciar la aplicación:\n\n" + traceback.format_exc(limit=3),
        )
        return 1

    window.show()

    from PySide6.QtCore import QTimer

    def _wait_threads() -> None:
        from linux_optimizer.ui.widgets import wait_for_workers
        wait_for_workers()

    app.aboutToQuit.connect(_wait_threads)
    return app.exec()
