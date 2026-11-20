"""Proceso independiente que muestra el HUD flotante.

Se lanza desde :class:`linux_optimizer.ui.hud_controller.HudController` con
``QT_QPA_PLATFORM=xcb`` para que la posición de la ventana sea real y pueda
recordarse entre sesiones incluso en Wayland (a través de XWayland).
"""

from __future__ import annotations

import signal
import sys

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from linux_optimizer import APP_NAME
from linux_optimizer.core.monitor import SystemMonitor
from linux_optimizer.logging_utils import setup_logging
from linux_optimizer.ui.hud_window import GamingHud


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv if argv is None else argv)
    setup_logging("=== HUD iniciado en proceso independiente ===")

    app = QApplication(argv)
    app.setApplicationName(f"{APP_NAME} HUD")
    app.setQuitOnLastWindowClosed(False)

    monitor = SystemMonitor()
    hud = GamingHud(monitor)
    hud.closed.connect(app.quit)

    def _stop(signum=None, _frame=None) -> None:
        app.quit()

    # El controlador cierra el HUD con SIGTERM; así se guarda la posición.
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            signal.signal(sig, _stop)
        except (ValueError, OSError):
            pass

    # Mantiene a Python al mando del bucle de Qt para atender las señales.
    tick = QTimer()
    tick.timeout.connect(lambda: None)
    tick.start(200)

    app.aboutToQuit.connect(hud.shutdown)
    app.aboutToQuit.connect(monitor.stop)

    hud.show()
    monitor.start()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
