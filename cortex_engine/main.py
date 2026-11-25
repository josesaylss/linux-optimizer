"""Sesión Cortex Gaming Engine de la aplicación Linux Optimizer.

Se abre con el mismo ejecutable:

    linux-optimizer --cortex
    python3 -m cortex_engine        (equivalente en desarrollo)

Cortex conserva su propia ventana, tema, configuración, monitor y registro;
cerrar Cortex no afecta a la sesión Linux Optimizer y viceversa.
"""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from cortex_engine import APP_NAME, APP_VERSION
from cortex_engine.interface.theme import CORTEX_QSS
from cortex_engine.interface.window import CortexWindow
from linux_optimizer.logging_utils import setup_logging


def _setup_logging() -> None:
    try:
        setup_logging(
            f"=== Inicio de la sesión {APP_NAME} {APP_VERSION} ===")
    except OSError:
        pass


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv if argv is None else argv)
    _setup_logging()
    app = QApplication.instance()
    embedded = app is not None
    if app is None:
        app = QApplication(argv)

    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(APP_VERSION)
    app.setOrganizationName("CortexGamingEngine")

    window = CortexWindow()
    if embedded:
        # Integración en un proceso existente (pruebas): el estilo se aplica
        # solo a esta ventana para no alterar la aplicación anfitriona.
        window.setStyleSheet(CORTEX_QSS)
    else:
        app.setStyle("Fusion")
        app.setStyleSheet(CORTEX_QSS)

    window.show()
    window.raise_()
    window.activateWindow()

    if embedded:
        return 0
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
