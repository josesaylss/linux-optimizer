"""Widgets reutilizables: tarjetas, sparklines, diálogos y hilos de trabajo."""

from __future__ import annotations

import logging
import time
from collections import deque

from PySide6.QtCore import QPointF, QRectF, QThread, Signal
from PySide6.QtGui import QColor, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


# ----------------------------------------------------------------------------
# Tarjetas
# ----------------------------------------------------------------------------

class Card(QFrame):
    """Contenedor con el estilo 'card' del tema."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("card")
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(16, 14, 16, 14)
        self._layout.setSpacing(10)

    @property
    def body(self) -> QVBoxLayout:
        return self._layout


class SectionTitle(QLabel):
    def __init__(self, text: str, parent: QWidget | None = None):
        super().__init__(text, parent)
        self.setObjectName("cardTitle")


class StatCard(QFrame):
    """Tarjeta de estadística: título, valor grande, subtítulo y barra opcional."""

    def __init__(self, title: str, subtitle: str = "", show_bar: bool = False,
                 parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("statCard")
        self.setMinimumHeight(110)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(4)

        title_row = QHBoxLayout()
        self.title_label = QLabel(title)
        self.title_label.setObjectName("cardTitle")
        title_row.addWidget(self.title_label)
        title_row.addStretch(1)
        self.extra_label = QLabel("")
        self.extra_label.setObjectName("statSubtitle")
        title_row.addWidget(self.extra_label)
        layout.addLayout(title_row)

        self.value_label = QLabel("—")
        self.value_label.setObjectName("statValue")
        layout.addWidget(self.value_label)

        self.subtitle_label = QLabel(subtitle)
        self.subtitle_label.setObjectName("statSubtitle")
        self.subtitle_label.setWordWrap(True)
        layout.addWidget(self.subtitle_label)

        self.bar: QProgressBar | None = None
        if show_bar:
            self.bar = QProgressBar()
            self.bar.setRange(0, 100)
            self.bar.setTextVisible(False)
            layout.addWidget(self.bar)
        layout.addStretch(1)

    def set_value(self, text: str, subtitle: str | None = None) -> None:
        self.value_label.setText(text)
        if subtitle is not None:
            self.subtitle_label.setText(subtitle)

    @property
    def body(self) -> QVBoxLayout:
        """Permite añadir widgets extra (p. ej. un sparkline)."""
        return self.layout()

    def set_percent(self, pct: float | None) -> None:
        if self.bar is None:
            return
        if pct is None:
            self.bar.setRange(0, 1)
            self.bar.setValue(0)
            return
        self.bar.setRange(0, 100)
        self.bar.setValue(int(max(0.0, min(100.0, pct))))


# ----------------------------------------------------------------------------
# Sparkline
# ----------------------------------------------------------------------------

class Sparkline(QWidget):
    """Mini gráfico de línea para historial de uso."""

    def __init__(self, points: int = 60, parent: QWidget | None = None):
        super().__init__(parent)
        self._series: deque[float] = deque(maxlen=points)
        self._color = QColor("#2f6df6")
        self.setMinimumHeight(46)

    def set_color(self, color: str) -> None:
        self._color = QColor(color)
        self.update()

    def add_point(self, value: float) -> None:
        self._series.append(max(0.0, min(100.0, value)))
        self.update()

    def clear(self) -> None:
        self._series.clear()
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt)
        super().paintEvent(event)
        if not self._series:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        w, h = self.width(), self.height()
        n = len(self._series)
        max_value = 100.0

        points = QPolygonF()
        for i, value in enumerate(self._series):
            x = w * (i / max(n - 1, 1))
            y = h - (h - 4) * (value / max_value) - 2
            points.append(QPointF(x, y))

        # Relleno suave bajo la curva.
        fill = QPolygonF(points)
        fill.append(QPointF(w, h))
        fill.append(QPointF(0, h))
        fill_color = QColor(self._color)
        fill_color.setAlpha(40)
        painter.setPen(QPen(self._color, 0))
        painter.setBrush(fill_color)
        painter.drawPolygon(fill)

        pen = QPen(self._color)
        pen.setWidthF(1.8)
        painter.setPen(pen)
        painter.setBrush(QColor(0, 0, 0, 0))
        painter.drawPolyline(points)
        painter.end()


# ----------------------------------------------------------------------------
# Hilos de trabajo (para no congelar la UI)
# ----------------------------------------------------------------------------

class Worker(QThread):
    """Ejecuta una función en segundo plano y emite done/error."""

    done = Signal(object)
    error = Signal(str)

    def __init__(self, fn, parent: QWidget | None = None):
        super().__init__(parent)
        self._fn = fn

    def run(self) -> None:  # pragma: no cover - hilo
        try:
            self.done.emit(self._fn())
        except Exception as exc:  # noqa: BLE001
            logging.getLogger("LinuxOptimizer.worker").exception(
                "Error en tarea de fondo")
            self.error.emit(f"{type(exc).__name__}: {exc}")

    def _unregister(self) -> None:
        _ACTIVE_WORKERS.discard(self)


# Registro de trabajadores activos: evita que Python recoja un QThread
# mientras se está ejecutando y permite esperarlos al cerrar la app.
_ACTIVE_WORKERS: set[Worker] = set()


def wait_for_workers(timeout_ms: int = 8000) -> None:
    """Espera a que terminen los hilos de trabajo pendientes (al cerrar)."""
    deadline = time.monotonic() + timeout_ms / 1000.0
    for worker in list(_ACTIVE_WORKERS):
        try:
            if not worker.isRunning():
                continue
            remaining = int(max(deadline - time.monotonic(), 0.0) * 1000)
            if remaining <= 0:
                break
            worker.wait(remaining)
        except RuntimeError:
            # El objeto C++ ya fue destruido (worker terminado y limpiado).
            pass
    _ACTIVE_WORKERS.clear()


def run_worker(
    button: QPushButton | None,
    fn,
    on_done,
    on_error,
    busy_text: str = "Trabajando…",
    parent: QWidget | None = None,
) -> Worker:
    """Ejecuta `fn` en segundo plano deshabilitando `button` mientras corre."""
    if button is not None:
        button.setEnabled(False)
        button.setText(busy_text)
    worker = Worker(fn, parent)
    _ACTIVE_WORKERS.add(worker)

    def _restore() -> None:
        if button is not None:
            button.setEnabled(True)

    def _on_done(result) -> None:
        _restore()
        on_done(result)

    def _on_error(message: str) -> None:
        _restore()
        on_error(message)

    worker.done.connect(_on_done)
    worker.error.connect(_on_error)
    worker.finished.connect(worker._unregister)
    worker.finished.connect(worker.deleteLater)
    worker.start()
    return worker


# ----------------------------------------------------------------------------
# Diálogos de confirmación (siempre antes de modificar el sistema)
# ----------------------------------------------------------------------------

def confirm(
    parent: QWidget,
    title: str,
    message: str,
    danger: bool = False,
    detail: str = "",
) -> bool:
    box = QMessageBox(QMessageBox.Question, title, message, parent=parent)
    box.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
    box.setDefaultButton(QMessageBox.No)
    if danger:
        yes = box.button(QMessageBox.Yes)
        yes.setObjectName("danger")
        yes.setText("Sí, aplicar")
        no = box.button(QMessageBox.No)
        no.setText("Cancelar")
    if detail:
        box.setDetailedText(detail)
    box.exec()
    return box.clickedButton() == box.button(QMessageBox.Yes)


def confirm_with_checkbox(
    parent: QWidget,
    title: str,
    message: str,
    checkbox_text: str,
    danger: bool = False,
) -> tuple[bool, bool]:
    """Diálogo de confirmación con una casilla; devuelve (confirmado, casilla)."""
    box = QMessageBox(QMessageBox.Question, title, message, parent=parent)
    box.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
    box.setDefaultButton(QMessageBox.No)
    checkbox = QCheckBox(checkbox_text)
    box.setCheckBox(checkbox)
    if danger:
        yes = box.button(QMessageBox.Yes)
        yes.setObjectName("danger")
        yes.setText("Sí, aplicar")
    box.exec()
    confirmed = box.clickedButton() == box.button(QMessageBox.Yes)
    return confirmed, checkbox.isChecked()


def info_dialog(parent: QWidget, title: str, message: str, detail: str = "") -> None:
    box = QMessageBox(QMessageBox.Information, title, message, parent=parent)
    box.setStandardButtons(QMessageBox.Ok)
    if detail:
        box.setDetailedText(detail)
    box.exec()


def error_dialog(parent: QWidget, title: str, message: str, detail: str = "") -> None:
    box = QMessageBox(QMessageBox.Critical, title, message, parent=parent)
    box.setStandardButtons(QMessageBox.Ok)
    if detail:
        box.setDetailedText(detail)
    box.exec()


def fmt_bytes(num: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(num) < 1024 or unit == "TB":
            return f"{num:,.1f} {unit}"
        num /= 1024
    return f"{num:,.1f} TB"


def fmt_rate(bps: float) -> str:
    return f"{fmt_bytes(bps)}/s"
