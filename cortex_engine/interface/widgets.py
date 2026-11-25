"""Widgets propios de la interfaz de Cortex Gaming Engine."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QProgressBar,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)


class Card(QFrame):
    """Tarjeta con el estilo verde de Cortex."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("cortexCard")
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(16, 14, 16, 14)
        self._layout.setSpacing(10)

    @property
    def body(self) -> QVBoxLayout:
        return self._layout


class SectionTitle(QLabel):
    def __init__(self, text: str, parent: QWidget | None = None):
        super().__init__(text.upper(), parent)
        self.setObjectName("sectionTitle")


class MetricTile(QFrame):
    """Valor grande con título, detalle y barra opcional."""

    def __init__(self, title: str, unit: str = "", show_bar: bool = False,
                 parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("metricTile")
        self._unit = unit
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(4)

        self.title_label = QLabel(title)
        self.title_label.setObjectName("sectionTitle")
        layout.addWidget(self.title_label)

        self.value_label = QLabel("—")
        self.value_label.setObjectName("metricValue")
        layout.addWidget(self.value_label)

        self.detail_label = QLabel("")
        self.detail_label.setObjectName("metricDetail")
        self.detail_label.setWordWrap(True)
        layout.addWidget(self.detail_label)

        self.bar: QProgressBar | None = None
        if show_bar:
            self.bar = QProgressBar()
            self.bar.setRange(0, 100)
            self.bar.setTextVisible(False)
            layout.addWidget(self.bar)
        layout.addStretch(1)

    def set_value(self, value: str, detail: str | None = None,
                  percent: float | None = None) -> None:
        self.value_label.setText(value)
        if detail is not None:
            self.detail_label.setText(detail)
        if self.bar is not None:
            if percent is None:
                self.bar.setRange(0, 1)
                self.bar.setValue(0)
            else:
                self.bar.setRange(0, 100)
                self.bar.setValue(int(max(0.0, min(100.0, percent))))


class Page(QWidget):
    """Página con cabecera y contenido desplazable."""

    def __init__(self, title: str, subtitle: str = "",
                 parent: QWidget | None = None):
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 18, 24, 14)
        outer.setSpacing(12)

        heading = QLabel(title)
        heading.setObjectName("pageTitle")
        outer.addWidget(heading)
        if subtitle:
            text = QLabel(subtitle)
            text.setObjectName("pageSubtitle")
            text.setWordWrap(True)
            outer.addWidget(text)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        content = QWidget()
        content.setObjectName("pageContent")
        self.body = QVBoxLayout(content)
        self.body.setContentsMargins(0, 4, 6, 4)
        self.body.setSpacing(14)
        scroll.setWidget(content)
        outer.addWidget(scroll, 1)


class ActivityList(QListWidget):
    """Lista de actividad que se actualiza sola."""

    def __init__(self, activity, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("activityList")
        self._activity = activity
        self.refresh()
        activity.changed.connect(self.refresh)

    def refresh(self) -> None:
        entries = self._activity.entries()[-200:]
        self.clear()
        self.addItems(reversed(entries))
        if self.count():
            self.scrollToTop()


class KeyValueRow(QWidget):
    """Fila compacta: etiqueta a la izquierda, valor acentuado a la derecha."""

    def __init__(self, label: str, value: str = "—",
                 parent: QWidget | None = None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        left = QLabel(label)
        left.setObjectName("muted")
        self.value_label = QLabel(value)
        self.value_label.setObjectName("accentValue")
        self.value_label.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(left)
        layout.addStretch(1)
        layout.addWidget(self.value_label)

    def set_value(self, value: str) -> None:
        self.value_label.setText(value)
