"""Control del HUD como proceso independiente.

En GNOME/Wayland una aplicación **no puede** colocar sus propias ventanas
(el compositor decide la posición y `move()`/`x()` no funcionan). Para que el
HUD recuerde exactamente dónde lo dejó el usuario y mantenga el bloqueo entre
sesiones, se ejecuta en un proceso aparte bajo **XWayland** (plataforma xcb),
donde las coordenadas sí son reales.
"""

from __future__ import annotations

import logging
import os
import sys
import time
from pathlib import Path

from PySide6.QtCore import (
    QObject,
    QProcess,
    QProcessEnvironment,
    QTimer,
    Signal,
)

from linux_optimizer.core.gamehud import find_latest_log
from linux_optimizer.core.hudstate import load_state, save_state

log = logging.getLogger("LinuxOptimizer.hud")

# Raíz del proyecto, para que el proceso hijo pueda importar el paquete.
ROOT = Path(__file__).resolve().parents[2]


class HudController(QObject):
    """Arranca y detiene el proceso del HUD; avisa cuando se cierra solo."""

    hidden = Signal()
    started = Signal()

    AUTO_INTERVAL_MS = 2000
    FRESH_SECS = 5.0
    HIDE_AFTER_SECS = 10.0

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self._stopping = False
        self._platform = "heredado"
        self.auto_enabled = bool(load_state().get("auto_show", True))
        self._auto_started = False
        self._suppress = False
        self._stale_ticks = 0
        self._process = QProcess(self)
        self._process.setProgram(sys.executable)
        self._process.setArguments(["-m", "linux_optimizer.hud_app"])
        self._process.setWorkingDirectory(str(ROOT))
        self._process.setProcessChannelMode(
            QProcess.ProcessChannelMode.MergedChannels)
        self._process.setProcessEnvironment(self._environment())
        self._process.finished.connect(self._on_finished)
        self._process.errorOccurred.connect(self._on_error)
        self._process.readyReadStandardOutput.connect(self._drain_output)
        self._process.started.connect(self.started)

        # Aparición automática: si un juego/app empieza a escribir FPS, se
        # muestra el HUD; al terminar (registro frío) se oculta solo.
        self._auto_timer = QTimer(self)
        self._auto_timer.setInterval(self.AUTO_INTERVAL_MS)
        self._auto_timer.timeout.connect(self._auto_tick)
        self._auto_timer.start()

    def _environment(self) -> QProcessEnvironment:
        env = QProcessEnvironment.systemEnvironment()
        pythonpath = env.value("PYTHONPATH")
        env.insert("PYTHONPATH", os.pathsep.join(
            part for part in (str(ROOT), pythonpath) if part))
        # XWayland permite posicionar la ventana con coordenadas reales.
        if env.value("DISPLAY"):
            env.insert("QT_QPA_PLATFORM", "xcb")
            self._platform = "xcb (XWayland)"
        else:
            self._platform = env.value("QT_QPA_PLATFORM") or "heredado"
        return env

    # ------------------------------------------------------------------
    # Ciclo de vida
    # ------------------------------------------------------------------

    def is_running(self) -> bool:
        return self._process.state() != QProcess.ProcessState.NotRunning

    def show(self) -> None:
        if self.is_running():
            return
        self._stopping = False
        self._suppress = False
        log.info("HUD: iniciando proceso independiente (plataforma %s)",
                 self._platform)
        self._process.start()

    def hide(self) -> None:
        # Ocultar a mano desactiva la reaparición automática durante la
        # partida actual (si no, volvería a mostrarse 2 s después).
        self._suppress = True
        self._auto_started = False
        self._terminate()

    def _auto_hide(self) -> None:
        self._auto_started = False
        self._terminate()

    def _terminate(self) -> None:
        if not self.is_running():
            return
        self._stopping = True
        log.info("HUD: deteniendo proceso")
        self._process.terminate()
        QTimer.singleShot(2500, self._kill_if_running)

    def toggle(self) -> None:
        self.hide() if self.is_running() else self.show()

    def shutdown(self) -> None:
        """Cierra el HUD y espera brevemente a que guarde su posición."""
        self._auto_timer.stop()
        self.hide()
        if self._process.state() != QProcess.ProcessState.NotRunning:
            if not self._process.waitForFinished(1500):
                self._process.kill()
                self._process.waitForFinished(500)

    # ------------------------------------------------------------------
    # Aparición automática con los juegos
    # ------------------------------------------------------------------

    def set_auto_enabled(self, enabled: bool) -> None:
        self.auto_enabled = bool(enabled)
        state = load_state()
        state["auto_show"] = self.auto_enabled
        save_state(state)
        log.info("HUD: aparición automática %s",
                 "activada" if self.auto_enabled else "desactivada")

    def _game_is_running(self) -> bool:
        latest = find_latest_log()
        if latest is None:
            return False
        try:
            return (time.time() - latest.stat().st_mtime) < self.FRESH_SECS
        except OSError:
            return False

    def _auto_tick(self) -> None:
        if self._game_is_running():
            self._stale_ticks = 0
            if (self.auto_enabled and not self.is_running()
                    and not self._suppress):
                log.info("HUD: juego detectado, mostrando automáticamente")
                self._auto_started = True
                self.show()
            return
        self._stale_ticks += 1
        if self._stale_ticks * (self.AUTO_INTERVAL_MS / 1000) < self.HIDE_AFTER_SECS:
            return
        # El registro lleva frío un rato: el juego terminó.
        self._suppress = False
        if self._auto_started and self.is_running():
            log.info("HUD: juego terminado, ocultando automáticamente")
            self._auto_hide()

    # ------------------------------------------------------------------
    # Señales del proceso
    # ------------------------------------------------------------------

    def _kill_if_running(self) -> None:
        if self._process.state() != QProcess.ProcessState.NotRunning:
            log.warning("HUD: el proceso no terminó a tiempo; se fuerza")
            self._process.kill()

    def _on_finished(self, code: int, status) -> None:
        user_closed = not self._stopping
        log.info("HUD: proceso terminado (código %s, %s)", code, status)
        self._stopping = False
        if user_closed:
            # Lo cerró el usuario con ✕: no reabrirlo hasta que termine la
            # partida actual.
            self._suppress = True
            self._auto_started = False
        # El usuario pudo cerrarlo con ✕: que la interfaz lo refleje.
        self.hidden.emit()

    def _on_error(self, error) -> None:
        if self._stopping and error == QProcess.ProcessError.Crashed:
            # SIGTERM al cerrar el HUD: no es un fallo real.
            return
        log.warning("HUD: error del proceso: %s", error)
        if error == QProcess.ProcessError.FailedToStart:
            self.hidden.emit()

    def _drain_output(self) -> None:
        raw = bytes(self._process.readAllStandardOutput()).decode(
            "utf-8", "replace")
        for line in raw.splitlines():
            if line.strip():
                log.info("HUD hijo: %s", line.strip()[:500])
