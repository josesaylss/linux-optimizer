"""HUD flotante de rendimiento para el Modo Gaming.

Overlay **transparente y minimalista** inspirado en MangoHud: solo los datos
(FPS, CPU, GPU, RAM, VRAM, temperaturas e hilos) en tipografía monoespaciada
con etiquetas de color y contorno oscuro para leerse sobre cualquier juego.

Se puede arrastrar con el ratón y **fijar** (botón de chincheta) para que no
se mueva por accidente. La posición y el estado de fijado se recuerdan entre
sesiones.

FPS:
  - Socket /tmp/mangoapp (gamescope --mangoapp), si existe.
  - Registros CSV de MangoHud en ~/.local/state/LinuxOptimizer/mangohud-logs
    (funciona con `mangohud %command%` + MANGOHUD_CONFIG=output_folder=...).
"""

from __future__ import annotations

import logging

from PySide6.QtCore import QPointF, Qt, QTimer, Signal
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
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from linux_optimizer.core.gamehud import MangoAppReader, MangoLogReader
from linux_optimizer.core.hudstate import load_state, save_state

log = logging.getLogger("LinuxOptimizer.hud")


HUD_QSS = """
#hudFps, #hudFpsUnit, #hudFrametime, #hudGame, #hudMetric, #hudMetricName,
#hudClose, #hudPin {
    background: transparent;
    border: none;
    font-family: "DejaVu Sans Mono", "Noto Sans Mono", "Liberation Mono", monospace;
}
#hudFps { font-size: 34px; font-weight: 800; }
#hudFpsUnit { font-size: 11px; font-weight: 700; }
#hudFrametime { font-size: 10px; }
#hudGame { font-size: 10px; font-weight: 700; }
#hudMetric { font-size: 12px; font-weight: 700; }
#hudMetricName { font-size: 12px; font-weight: 700; }
#hudClose { color: #9fb0cc; font-size: 13px; font-weight: 700; padding: 0; }
#hudClose:hover { color: #ff8080; }
#hudPin { color: #9fb0cc; font-size: 11px; padding: 0; }
#hudPin:hover { color: #ffffff; }
#hudPin:checked { color: #ffcf6b; }
"""


class OutlinedLabel(QLabel):
    """Texto sin fondo, con contorno oscuro para leerse sobre el juego."""

    def __init__(self, text: str = "", color: str = "#ffffff",
                 parent: QWidget | None = None):
        super().__init__(text, parent)
        self._color = QColor(color)
        # El tema global de la app pinta fondo oscuro en los QLabel; aquí se
        # anula para que el HUD sea realmente transparente.
        self.setStyleSheet("background: transparent; border: none;")
        self.setAutoFillBackground(False)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
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
        rect = self.contentsRect()
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


class _PinButton(QPushButton):
    """Botón de fijar dibujado a mano (sin depender de emojis del sistema)."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__("", parent)
        self.setCheckable(True)
        self.setFixedSize(18, 18)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setAccessibleName("Fijar el HUD")

    def paintEvent(self, event):  # noqa: N802 (Qt)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        if self.isChecked():
            color = QColor("#ffcf6b")
        elif self.underMouse():
            color = QColor("#ffffff")
        else:
            color = QColor("#9fb0cc")
        cx = self.width() / 2
        cy = self.height() / 2
        path = QPainterPath()
        # Cabeza de la chincheta (círculo) y aguja hacia abajo.
        path.addEllipse(QPointF(cx, cy - 3.0), 3.4, 3.4)
        painter.setPen(QPen(color, 1.7, Qt.PenStyle.SolidLine,
                            Qt.PenCapStyle.RoundCap))
        if self.isChecked():
            painter.setBrush(QBrush(color))
        else:
            painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(path)
        painter.drawLine(QPointF(cx, cy + 0.2), QPointF(cx, cy + 5.8))
        painter.drawLine(QPointF(cx - 2.4, cy + 6.2), QPointF(cx + 2.4, cy + 6.2))


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
        self._hud._end_drag()
        super().mouseReleaseEvent(event)


class GamingHud(QWidget):
    """Overlay compacto: FPS + GPU + CPU + RAM."""

    closed = Signal()

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
        self._state = load_state()
        self._locked = bool(self._state.get("locked"))
        # En Wayland el compositor manda: x()/y() siempre valen 0 y move() no
        # hace nada. El HUD se lanza en XWayland (xcb) precisamente para que
        # la posición sea real y se pueda recordar.
        self._positionable = not QGuiApplication.platformName().startswith(
            "wayland")
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(400)
        self._save_timer.timeout.connect(self._save_state)

        panel = _HudPanel(self)
        self._panel = panel

        layout = QVBoxLayout(panel)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(0)

        # --- Cabecera: juego + fijar + cerrar -------------------------
        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(6)
        self._game_label = OutlinedLabel("SIN JUEGO", "#9fb0cc")
        self._game_label.setObjectName("hudGame")
        top.addWidget(self._game_label, 1)
        self._pin_btn = _PinButton()
        self._pin_btn.setObjectName("hudPin")
        self._pin_btn.setToolTip("Fijar el HUD en esta posición")
        self._pin_btn.toggled.connect(self._set_locked)
        top.addWidget(self._pin_btn, 0, Qt.AlignmentFlag.AlignTop)
        close_btn = QPushButton("✕")
        close_btn.setObjectName("hudClose")
        close_btn.setFixedSize(16, 16)
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.clicked.connect(self._close_clicked)
        top.addWidget(close_btn, 0, Qt.AlignmentFlag.AlignTop)
        layout.addLayout(top)

        # --- FPS ------------------------------------------------------
        fps_row = QHBoxLayout()
        fps_row.setContentsMargins(0, 0, 0, 0)
        fps_row.setSpacing(5)
        self._fps_label = OutlinedLabel("—", "#ffffff")
        self._fps_label.setObjectName("hudFps")
        self._fps_label.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        fps_row.addWidget(self._fps_label, 0, Qt.AlignmentFlag.AlignBottom)
        self._fps_unit = OutlinedLabel("FPS", "#9fb8e6")
        self._fps_unit.setObjectName("hudFpsUnit")
        fps_row.addWidget(self._fps_unit, 0, Qt.AlignmentFlag.AlignBottom)
        self._frametime = OutlinedLabel("", "#aeb8cc")
        self._frametime.setObjectName("hudFrametime")
        fps_row.addWidget(self._frametime, 0, Qt.AlignmentFlag.AlignBottom)
        fps_row.addStretch(1)
        layout.addLayout(fps_row)

        # --- Datos al estilo MangoHud ---------------------------------
        grid = QGridLayout()
        grid.setContentsMargins(0, 2, 0, 0)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(0)
        grid.setColumnMinimumWidth(0, 46)
        self._rows: dict[str, OutlinedLabel] = {}
        for i, (key, name, color) in enumerate((
            ("cpu", "CPU", "#7fb3ff"),
            ("gpu", "GPU", "#ffb454"),
            ("ram", "RAM", "#b8c4d8"),
            ("vram", "VRAM", "#b8c4d8"),
            ("temp", "TEMP", "#ff9d6b"),
            ("threads", "THR", "#9fe08a"),
        )):
            name_label = OutlinedLabel(name, color)
            name_label.setObjectName("hudMetricName")
            value = OutlinedLabel("—", "#ffffff")
            value.setObjectName("hudMetric")
            grid.addWidget(name_label, i, 0)
            grid.addWidget(value, i, 1)
            self._rows[key] = value
        grid.setColumnStretch(1, 1)
        layout.addLayout(grid)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(panel)

        hint = self.sizeHint()
        self.resize(max(200, hint.width()), max(120, hint.height()))
        self._reader.metrics_updated.connect(self._on_game_metrics)
        self._log_reader.metrics_updated.connect(self._on_game_metrics)
        monitor.stats_updated.connect(self._on_system_stats)

        self._pin_btn.blockSignals(True)
        self._pin_btn.setChecked(self._locked)
        self._pin_btn.blockSignals(False)
        self._apply_lock_ui()
        self.setToolTip("Arrastra para mover · botón de pin: fijar · ✕ cerrar")

    # ------------------------------------------------------------------
    # Visibilidad y posición
    # ------------------------------------------------------------------

    def showEvent(self, event):  # noqa: N802 (Qt)
        super().showEvent(event)
        # Recordar dónde lo dejó el usuario. Solo tiene efecto real cuando la
        # plataforma permite posicionar ventanas (xcb/X11).
        if self._positionable:
            x, y = self._state.get("x"), self._state.get("y")
            if x is not None and y is not None:
                self.move(int(x), int(y))
                QTimer.singleShot(700, self._log_position)
            else:
                # Primera vez: esquina superior derecha, como MangoHud.
                screen = QGuiApplication.primaryScreen()
                if screen is not None:
                    area = screen.availableGeometry()
                    self.move(area.right() - self.width() - 24,
                              area.top() + 24)
                    QTimer.singleShot(700, self._log_position)
        self.raise_()
        self._align_fps_annotations()
        QTimer.singleShot(0, self._align_fps_annotations)
        if not self._reader.isRunning():
            self._reader.start()
        if not self._log_reader.isRunning():
            self._log_reader.start()

    def _close_clicked(self) -> None:
        """✕ del HUD: se oculta y avisa para que el proceso termine."""
        self.hide()
        self.closed.emit()

    def _log_position(self) -> None:
        if not self._positionable:
            log.info("HUD: el compositor (%s) controla la posición",
                     QGuiApplication.platformName())
            return
        saved = (self._state.get("x"), self._state.get("y"))
        current = (self.x(), self.y())
        if saved[0] is not None and current != saved:
            log.info(
                "HUD: no se pudo restaurar la posición (guardada %s, "
                "actual %s) en %s",
                saved, current, QGuiApplication.platformName(),
            )
        else:
            log.info("HUD: posición restaurada %s (%s)",
                     current, QGuiApplication.platformName())

    def _save_state(self) -> None:
        # Se relee el archivo para conservar «auto_show», que puede haberse
        # cambiado desde la ventana principal.
        state = load_state()
        state["locked"] = self._locked
        if self._positionable:
            state["x"], state["y"] = self.x(), self.y()
        self._state = state
        save_state(state)

    def moveEvent(self, event):  # noqa: N802 (Qt)
        super().moveEvent(event)
        if self._positionable:
            # Guardado con retardo: durante el arrastre hay decenas de eventos
            # de movimiento y no conviene escribir el JSON en cada uno.
            self._save_timer.start()

    def hideEvent(self, event):  # noqa: N802 (Qt)
        super().hideEvent(event)
        self._save_state()
        # No se detienen los hilos aquí: esperarlos bloquearía la interfaz
        # hasta 3 s (causa de que el HUD pareciera "trabado" al cerrarlo).

    def shutdown(self) -> None:
        """Detiene los lectores al cerrar la aplicación."""
        self._save_state()
        self._reader.stop()
        self._log_reader.stop()

    def toggle(self) -> None:
        self.hide() if self.isVisible() else self.show()

    # ------------------------------------------------------------------
    # Fijado
    # ------------------------------------------------------------------

    def _set_locked(self, locked: bool) -> None:
        self._locked = bool(locked)
        self._apply_lock_ui()
        self._save_state()
        log.info("HUD: %s", "fijado" if self._locked else "desbloqueado")

    def _apply_lock_ui(self) -> None:
        self._panel.setCursor(
            Qt.CursorShape.ArrowCursor if self._locked
            else Qt.CursorShape.SizeAllCursor
        )
        self._pin_btn.setToolTip(
            "HUD fijado: no se mueve (pulsa para desbloquear)"
            if self._locked else "Fijar el HUD en esta posición"
        )

    # ------------------------------------------------------------------
    # Datos
    # ------------------------------------------------------------------

    def _on_game_metrics(self, payload: dict) -> None:
        if payload.get("stale"):
            # El juego terminó: no dejar FPS congelados en pantalla.
            self._fps_label.setText("—")
            self._frametime.setText("")
            self._game_label.setText("SIN JUEGO")
            self._game_label.setTextColor("#9fb0cc")
            self._fit_width()
            return
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

    def _on_system_stats(self, stats: dict) -> None:
        cpu = stats["cpu"]
        per_core = cpu.get("per_core") or []
        cores = " ".join(f"{value:.0f}" for value in per_core)
        self._rows["cpu"].setText(f"{cpu['percent']:.0f}%  {cores}".rstrip())

        mem = stats["mem"]
        self._rows["ram"].setText(
            f"{mem['percent']:.0f}%  "
            f"{mem['used'] / 1024**2:.0f}/{mem['total'] / 1024**2:.0f} MB"
        )

        gpu_stats = stats.get("gpus") or []
        if gpu_stats:
            g = gpu_stats[0]
            util = f"{g['util']:.0f}%"
            if g.get("temp"):
                util += f"  {g['temp']:.0f}°C"
            self._rows["gpu"].setText(util)
            if g.get("mem_total_mb"):
                pct = (g.get("mem_used_mb") or 0) * 100 / g["mem_total_mb"]
                self._rows["vram"].setText(
                    f"{pct:.0f}%  {g.get('mem_used_mb') or 0:.0f}/"
                    f"{g['mem_total_mb']:.0f} MB"
                )
            else:
                self._rows["vram"].setText("—")
        else:
            self._rows["gpu"].setText("—")
            self._rows["vram"].setText("—")

        temps = stats.get("temps") or []
        cpu_temp = self._pick_temp(temps, ("tctl", "package", "coretemp", "k10temp", "cpu"))
        soc_temp = gpu_stats[0].get("temp") if gpu_stats else None
        if not soc_temp:
            soc_temp = self._pick_temp(temps, ("edge", "junction", "soc", "gpu"))
        parts = []
        if cpu_temp:
            parts.append(f"CPU {cpu_temp:.0f}°C")
        if soc_temp:
            parts.append(f"SOC {soc_temp:.0f}°C")
        self._rows["temp"].setText("  ".join(parts) or "—")

        threads = stats.get("threads")
        self._rows["threads"].setText(f"{threads}" if threads else "—")
        self._fit_width()

    @staticmethod
    def _pick_temp(temps: list[tuple[str, float]], needles: tuple[str, ...]) -> float | None:
        """Elige la temperatura cuyo sensor coincide con alguno de los nombres."""
        for name, value in temps:
            low = name.lower()
            if any(needle in low for needle in needles):
                return value
        return None

    def _align_fps_annotations(self) -> None:
        """Alinea «FPS» y los ms con la línea base del número grande."""
        height = self._fps_label.height()
        if not 20 <= height <= 120:
            return
        big = self._fps_label.fontMetrics()
        baseline = (height + big.ascent() - big.descent()) / 2
        for label in (self._fps_unit, self._frametime):
            fm = label.fontMetrics()
            small = int(round(2 * (height - baseline) + fm.ascent() - fm.descent()))
            label.setFixedHeight(max(small, fm.height()))

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
        self._align_fps_annotations()

    # ------------------------------------------------------------------
    # Arrastre (Wayland: startSystemMove; X11: move() manual)
    # ------------------------------------------------------------------

    def _begin_drag(self, event) -> None:
        if self._locked:
            return
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
        log.info("HUD: arrastre manual (%s)", QGuiApplication.platformName())

    def _drag_move(self, event) -> None:
        if (
            self._drag_offset is not None
            and event.buttons() & Qt.MouseButton.LeftButton
        ):
            self.move(event.globalPosition().toPoint() - self._drag_offset)

    def _end_drag(self) -> None:
        self._drag_offset = None
        # Guarda la nueva posición para futuras sesiones.
        self._save_state()
