"""HUD flotante de rendimiento para el Modo Gaming.

Overlay **totalmente transparente y minimalista**: no hay panel, ni borde,
ni fondo; solo los datos (FPS, CPU, RAM, GPU y temperatura) con un contorno
oscuro para que se lean sobre cualquier juego.

Arrastre:
  - Wayland: startSystemMove() del compositor (move() no funciona en
    ventanas de nivel superior en Wayland).
  - X11: movimiento manual con la posición global del ratón.

FPS:
  - Socket /tmp/mangoapp (gamescope --mangoapp), si existe.
  - Registros CSV de MangoHud en ~/.local/state/LinuxOptimizer/mangohud-logs
    (funciona con `mangohud %command%` + MANGOHUD_CONFIG=output_folder=...).
"""

from __future__ import annotations

import logging

from PySide6.QtCore import Qt
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFontMetrics,
    QGuiApplication,
    QPainter,
    QPainterPath,
    QPen,
)
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from linux_optimizer.core.gamehud import MangoAppReader, MangoLogReader

log = logging.getLogger("LinuxOptimizer.hud")


HUD_QSS = """
#hudFps { font-size: 38px; font-weight: 800; }
#hudFpsUnit { font-size: 11px; font-weight: 700; }
#hudFrametime { font-size: 10px; }
#hudGame { font-size: 10px; font-weight: 700; }
#hudMetric { font-size: 11px; font-weight: 700; }
#hudClose { color: #ffffff; border: none; background: transparent;
            font-size: 13px; font-weight: 700; padding: 0; }
#hudClose:hover { color: #ff8080; }
"""


class OutlinedLabel(QLabel):
    """Texto sin fondo, con contorno oscuro para leerse sobre el juego."""

    def __init__(self, text: str = "", color: str = "#ffffff",
                 parent: QWidget | None = None):
        super().__init__(text, parent)
        self._color = QColor(color)
        # El texto nunca debe capturar el ratón: así el HUD se arrastra
        # desde cualquier punto.
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

    def setTextColor(self, color: str) -> None:
        self._color = QColor(color)
        self.update()

    def paintEvent(self, event):  # noqa: N802 (Qt)
        text = self.text()
        if not text:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)

        fm = QFontMetrics(self.font())
        width = fm.horizontalAdvance(text)
        rect = self.rect()
        align = int(self.alignment())
        if align & int(Qt.AlignmentFlag.AlignHCenter):
            x = rect.x() + (rect.width() - width) / 2
        elif align & int(Qt.AlignmentFlag.AlignRight):
            x = rect.right() - width
        else:
            x = rect.x()
        baseline = rect.y() + (rect.height() + fm.ascent() - fm.descent()) / 2

        path = QPainterPath()
        path.addText(float(x), float(baseline), self.font(), text)
        # Contorno negro + relleno: legible sin caja ni fondo.
        painter.strokePath(
            path,
            QPen(QColor(0, 0, 0, 210), 3.4, Qt.PenStyle.SolidLine,
                 Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin),
        )
        painter.fillPath(path, QBrush(self._color))


class _HudPanel(QWidget):
    """Superficie transparente que reenvía el ratón para arrastrar el HUD."""

    def __init__(self, hud: "GamingHud"):
        super().__init__(hud)
        self._hud = hud
        self.setCursor(Qt.CursorShape.SizeAllCursor)

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
    """Overlay minimalista: FPS grandes + una línea de métricas."""

    def __init__(self, monitor, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("Linux Optimizer — HUD")
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            # No robar el foco al juego al pulsar el HUD para arrastrarlo.
            | Qt.WindowType.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setStyleSheet(HUD_QSS)
        self._drag_offset = None
        self._monitor = monitor
        self._reader = MangoAppReader()
        self._log_reader = MangoLogReader()

        panel = _HudPanel(self)
        self._panel = panel

        layout = QVBoxLayout(panel)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(0)

        # --- Cabecera: juego + cerrar --------------------------------
        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(6)
        self._game_label = OutlinedLabel("SIN JUEGO DETECTADO", "#cfd8ea")
        self._game_label.setObjectName("hudGame")
        top.addWidget(self._game_label, 1)
        close_btn = QPushButton("✕")
        close_btn.setObjectName("hudClose")
        close_btn.setFixedSize(18, 18)
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.clicked.connect(self.hide)
        top.addWidget(close_btn, 0, Qt.AlignmentFlag.AlignTop)
        layout.addLayout(top)

        # --- FPS ------------------------------------------------------
        fps_row = QHBoxLayout()
        fps_row.setContentsMargins(0, 0, 0, 0)
        fps_row.setSpacing(4)
        self._fps_label = OutlinedLabel("—", "#ffffff")
        self._fps_label.setObjectName("hudFps")
        self._fps_label.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        fps_row.addWidget(self._fps_label, 0)
        unit_col = QVBoxLayout()
        unit_col.setContentsMargins(0, 0, 0, 0)
        unit_col.setSpacing(0)
        unit_col.addStretch(1)
        self._fps_unit = OutlinedLabel("FPS", "#9fb8e6")
        self._fps_unit.setObjectName("hudFpsUnit")
        unit_col.addWidget(self._fps_unit)
        self._frametime = OutlinedLabel("", "#aeb8cc")
        self._frametime.setObjectName("hudFrametime")
        unit_col.addWidget(self._frametime)
        fps_row.addLayout(unit_col, 0)
        fps_row.addStretch(1)
        layout.addLayout(fps_row)

        # --- Métricas en una sola línea -------------------------------
        metrics_row = QHBoxLayout()
        metrics_row.setContentsMargins(0, 0, 0, 0)
        metrics_row.setSpacing(10)
        self._rows: dict[str, OutlinedLabel] = {}
        for key in ("cpu", "gpu", "ram", "temp"):
            value = OutlinedLabel("—", "#f2f5fb")
            value.setObjectName("hudMetric")
            metrics_row.addWidget(value, 0)
            self._rows[key] = value
        metrics_row.addStretch(1)
        layout.addLayout(metrics_row)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(panel)

        self.resize(230, 96)
        self._reader.metrics_updated.connect(self._on_game_metrics)
        self._log_reader.metrics_updated.connect(self._on_game_metrics)
        monitor.stats_updated.connect(self._on_system_stats)

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

    def shutdown(self) -> None:
        """Detiene los lectores al cerrar la aplicación."""
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
                self._frametime.setText(f"{frame:.1f} ms")
        name = payload.get("app") or ""
        if name:
            self._game_label.setText(name.upper())
            self._game_label.setTextColor("#dfe6f4")
        self._fit_width()

    def _fit_width(self) -> None:
        """Crece el ancho si el texto actual no cabe (nunca se encoge)."""
        panel_layout = self._panel.layout()
        if panel_layout is not None:
            panel_layout.activate()
        layout = self.layout()
        if layout is not None:
            layout.activate()
        need = self.sizeHint().width()
        if need > self.width():
            self.resize(need, max(self.height(), self.sizeHint().height()))

    def _on_system_stats(self, stats: dict) -> None:
        cpu = stats["cpu"]
        self._rows["cpu"].setText(f"CPU {cpu['percent']:.0f}%")

        mem = stats["mem"]
        self._rows["ram"].setText(
            f"RAM {mem['used'] / 1024**3:.1f}/{mem['total'] / 1024**3:.0f}G"
        )

        gpu_stats = stats.get("gpus") or []
        if gpu_stats:
            g = gpu_stats[0]
            self._rows["gpu"].setText(f"GPU {g['util']:.0f}%")
        else:
            self._rows["gpu"].setText("GPU —")

        temps = stats.get("temps") or []
        if temps:
            _name, value = max(temps, key=lambda item: item[1])
            self._rows["temp"].setText(f"{value:.0f}°C")
        else:
            self._rows["temp"].setText("—")
        self._fit_width()

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
