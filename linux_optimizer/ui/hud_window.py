"""HUD flotante de rendimiento para el Modo Gaming.

Ventana sin marco, siempre visible y translúcida que muestra FPS reales
(vía MangoHud) junto con CPU, RAM, GPU y temperatura en vivo.

Arrastre:
  - Wayland: usa startSystemMove() del compositor (move() no funciona en
    ventanas de nivel superior en Wayland).
  - X11: movimiento manual con la posición global del ratón.

FPS:
  - Socket /tmp/mangoapp (gamescope --mangoapp), si existe.
  - Registros CSV de MangoHud en ~/.local/state/LinuxOptimizer/mangohud-logs
    (funciona con `mangohud %command%` + MANGOHUD_CONFIG=output_folder=...).
"""

from __future__ import annotations

import logging

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from linux_optimizer.core.gamehud import MangoAppReader, MangoLogReader

log = logging.getLogger("LinuxOptimizer.hud")


HUD_QSS = """
#hudPanel {
    background-color: rgba(13, 16, 24, 235);
    border: 1px solid rgba(47, 109, 246, 140);
    border-radius: 14px;
}
#hudTitle { color: #8b95ad; font-size: 10px; font-weight: 700; letter-spacing: 2px; }
#hudFps { color: #ffffff; font-size: 34px; font-weight: 800; }
#hudFpsUnit { color: #7fb3ff; font-size: 12px; }
#hudFrametime { color: #7d879d; font-size: 10px; }
#hudGame { color: #dfe4ee; font-size: 12px; font-weight: 600; }
#hudMetric { color: #9aa4bb; font-size: 11px; }
#hudValue { color: #ffffff; font-size: 13px; font-weight: 700; }
#hudClose { color: #9aa4bb; border: none; background: transparent; font-size: 13px; padding: 0; }
#hudClose:hover { color: #ffffff; }
"""


class _HudPanel(QWidget):
    """Panel que reenvía los eventos del ratón a la ventana para arrastrarla."""

    def __init__(self, hud: "GamingHud"):
        super().__init__(hud)
        self._hud = hud

    def mousePressEvent(self, event):  # noqa: N802 (Qt)
        if event.button() == Qt.MouseButton.LeftButton:
            self._hud._begin_drag(event)
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):  # noqa: N802 (Qt)
        self._hud._drag_move(event)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):  # noqa: N802 (Qt)
        self._hud._drag_offset = None
        super().mouseReleaseEvent(event)


class GamingHud(QWidget):
    """Overlay compacto: FPS + CPU + RAM + GPU + temperatura."""

    def __init__(self, monitor, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("Linux Optimizer — HUD")
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._drag_offset = None
        self._monitor = monitor
        self._reader = MangoAppReader()
        self._log_reader = MangoLogReader()

        panel = _HudPanel(self)
        panel.setObjectName("hudPanel")
        panel.setStyleSheet(HUD_QSS)
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(14, 10, 14, 12)
        panel_layout.setSpacing(4)

        # Cabecera
        top = QHBoxLayout()
        title = QLabel("MODO GAMING")
        title.setObjectName("hudTitle")
        top.addWidget(title)
        top.addStretch(1)
        close_btn = QPushButton("✕")
        close_btn.setObjectName("hudClose")
        close_btn.setFixedSize(20, 20)
        close_btn.clicked.connect(self.hide)
        top.addWidget(close_btn)
        panel_layout.addLayout(top)

        # FPS
        fps_row = QHBoxLayout()
        self._fps_label = QLabel("—")
        self._fps_label.setObjectName("hudFps")
        self._fps_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        fps_unit = QLabel("FPS")
        fps_unit.setObjectName("hudFpsUnit")
        self._frametime = QLabel("")
        self._frametime.setObjectName("hudFrametime")
        self._frametime.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom)
        fps_col = QVBoxLayout()
        fps_col.addWidget(self._fps_label)
        fps_col.addWidget(self._frametime)
        fps_row.addLayout(fps_col, 1)
        fps_row.addWidget(fps_unit, 0, Qt.AlignmentFlag.AlignBottom)
        panel_layout.addLayout(fps_row)

        self._game_label = QLabel("sin juego con MangoHud detectado")
        self._game_label.setObjectName("hudGame")
        panel_layout.addWidget(self._game_label)

        # Métricas
        grid = QGridLayout()
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(2)
        self._rows: dict[str, QLabel] = {}
        metrics = [("cpu", "CPU"), ("ram", "RAM"), ("gpu", "GPU"), ("temp", "TEMP")]
        for i, (key, name) in enumerate(metrics):
            label = QLabel(name)
            label.setObjectName("hudMetric")
            value = QLabel("—")
            value.setObjectName("hudValue")
            grid.addWidget(label, i // 2, (i % 2) * 2)
            grid.addWidget(value, i // 2, (i % 2) * 2 + 1)
            self._rows[key] = value
        panel_layout.addLayout(grid)

        # Los textos no deben capturar el ratón: así se puede arrastrar
        # desde cualquier punto del panel (el botón ✕ sigue funcionando).
        for label in panel.findChildren(QLabel):
            label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(panel)

        self.resize(240, 150)
        self._reader.metrics_updated.connect(self._on_game_metrics)
        self._log_reader.metrics_updated.connect(self._on_game_metrics)
        monitor.stats_updated.connect(self._on_system_stats)

        # Repintado periódico: en Wayland una ventana translúcida sin marco a
        # veces no se redibuja si solo cambian textos; esto evita que el HUD
        # parezca "congelado".
        self._repaint_timer = QTimer(self)
        self._repaint_timer.setInterval(1000)
        self._repaint_timer.timeout.connect(self.update)
        self._repaint_timer.start()

        self.setToolTip("Arrastra para mover el HUD · ✕ para cerrarlo")

    # ------------------------------------------------------------------
    # Visibilidad
    # ------------------------------------------------------------------

    def showEvent(self, event):  # noqa: N802 (Qt)
        super().showEvent(event)
        if not self._reader.isRunning():
            self._reader.start()
        if not self._log_reader.isRunning():
            self._log_reader.start()

    def hideEvent(self, event):  # noqa: N802 (Qt)
        super().hideEvent(event)
        # No se detienen los hilos aquí: esperarlos bloquearía la interfaz
        # hasta 3 s (causa de que el HUD pareciera "trabado" al cerrarlo).
        # Siguen leyendo en segundo plano y se paran en shutdown().

    def shutdown(self) -> None:
        """Detiene los lectores al cerrar la aplicación."""
        self._repaint_timer.stop()
        self._reader.stop()
        self._log_reader.stop()

    def toggle(self) -> None:
        self.hide() if self.isVisible() else self.show()

    # ------------------------------------------------------------------
    # Datos
    # ------------------------------------------------------------------

    def _on_game_metrics(self, payload: dict) -> None:
        fps = payload.get("fps")
        if fps is not None and fps > 0:
            self._fps_label.setText(f"{fps:.0f}")
            frame = payload.get("frametime_ms")
            if frame:
                self._frametime.setText(f"{frame:.1f} ms por fotograma")
        name = payload.get("app") or ""
        if name:
            self._game_label.setText(name)

    def _on_system_stats(self, stats: dict) -> None:
        cpu = stats["cpu"]
        self._rows["cpu"].setText(f"{cpu['percent']:.0f}%")

        mem = stats["mem"]
        self._rows["ram"].setText(
            f"{mem['used'] / 1024**3:.1f}/{mem['total'] / 1024**3:.0f} GB"
        )

        gpu_stats = stats.get("gpus") or []
        if gpu_stats:
            g = gpu_stats[0]
            gpu_text = f"{g['util']:.0f}%"
            if g.get("mem_total_mb"):
                gpu_text += f" · {g['mem_used_mb']:.0f} MB"
            if g.get("temp"):
                gpu_text += f" · {g['temp']:.0f}°C"
            self._rows["gpu"].setText(gpu_text)
        else:
            self._rows["gpu"].setText("—")

        temps = stats.get("temps") or []
        if temps:
            _name, value = max(temps, key=lambda item: item[1])
            self._rows["temp"].setText(f"{value:.0f}°C")
        else:
            self._rows["temp"].setText("—")

    # ------------------------------------------------------------------
    # Arrastre (Wayland: startSystemMove; X11: move() manual)
    # ------------------------------------------------------------------

    def _begin_drag(self, event) -> None:
        # Posición de respaldo para el arrastre manual (X11).
        self._drag_offset = (
            event.globalPosition().toPoint() - self.frameGeometry().topLeft()
        )
        window = self.windowHandle()
        if window is None:
            # En Wayland la ventana nativa debe existir antes de pedir el
            # movimiento al compositor.
            self.createWinId()
            window = self.windowHandle()
        if window is not None:
            try:
                if window.startSystemMove():
                    self._drag_offset = None
                    log.info(
                        "HUD: arrastre gestionado por el compositor (%s)",
                        QGuiApplication.platformName(),
                    )
                    return
            except (AttributeError, RuntimeError) as exc:
                log.info("HUD: startSystemMove no disponible (%s)", exc)
        log.info(
            "HUD: arrastre manual (%s)", QGuiApplication.platformName()
        )

    def _drag_move(self, event) -> None:
        if (
            self._drag_offset is not None
            and event.buttons() & Qt.MouseButton.LeftButton
        ):
            self.move(event.globalPosition().toPoint() - self._drag_offset)
