"""Página de herramientas de diagnóstico (solo lectura)."""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QVBoxLayout,
    QWidget,
)

from linux_optimizer.core import diagnostics
from linux_optimizer.ui.widgets import Card, run_worker, SectionTitle


SEVERITY_COLORS = {
    "ok": "#58d68d",
    "info": "#7fb3ff",
    "warn": "#f5b041",
    "crit": "#ff6b6b",
}


class DiagnosticsPage(QWidget):
    def __init__(self, distro_info, parent: QWidget | None = None):
        super().__init__(parent)
        self._checks: list[diagnostics.CheckResult] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 18, 24, 18)
        layout.setSpacing(12)

        title = QLabel("Diagnóstico del sistema")
        title.setObjectName("headerTitle")
        layout.addWidget(title)
        subtitle = QLabel(
            "Todas las comprobaciones son de solo lectura: no modifican nada del "
            "sistema. Se priorizan los problemas más graves."
        )
        subtitle.setObjectName("headerSubtitle")
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)

        list_card = Card()
        list_card.body.addWidget(SectionTitle("Resultados"))
        self._list = QListWidget()
        self._list.currentRowChanged.connect(self._show_detail)
        list_card.body.addWidget(self._list)
        layout.addWidget(list_card, 2)

        detail_card = Card()
        detail_card.body.addWidget(SectionTitle("Detalle"))
        self._detail = QPlainTextEdit()
        self._detail.setReadOnly(True)
        detail_card.body.addWidget(self._detail)
        layout.addWidget(detail_card, 3)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self._copy_btn = QPushButton("Copiar informe")
        self._copy_btn.clicked.connect(self._copy_report)
        buttons.addWidget(self._copy_btn)
        self._refresh_btn = QPushButton("Ejecutar diagnóstico")
        self._refresh_btn.setObjectName("primary")
        self._refresh_btn.clicked.connect(self.refresh)
        buttons.addWidget(self._refresh_btn)
        layout.addLayout(buttons)

        self.refresh()

    def refresh(self) -> None:
        self._refresh_btn.setEnabled(False)
        self._refresh_btn.setText("Analizando…")

        def done(result):
            self._refresh_btn.setEnabled(True)
            self._refresh_btn.setText("Ejecutar diagnóstico")
            self._checks = result
            self._render()

        def error(message):
            self._refresh_btn.setEnabled(True)
            self._refresh_btn.setText("Ejecutar diagnóstico")
            self._detail.setPlainText("Error durante el diagnóstico:\n" + message)

        run_worker(self._refresh_btn, diagnostics.run_checks, done, error,
                   "Analizando…", self)

    def _render(self) -> None:
        self._list.clear()
        for check in self._checks:
            item = QListWidgetItem(f"{check.icon}  {check.name} — {check.severity.upper()}")
            item.setData(Qt.UserRole, check)
            self._list.addItem(item)
        if self._checks:
            self._list.setCurrentRow(0)

    def _show_detail(self, row: int) -> None:
        if row < 0 or row >= len(self._checks):
            return
        check = self._checks[row]
        self._detail.setPlainText(check.detail)

    def _copy_report(self) -> None:
        if not self._checks:
            return
        QGuiApplication.clipboard().setText(diagnostics.format_report(self._checks))
        self._copy_btn.setText("✔ Copiado")
        QTimer.singleShot(2000, lambda: self._copy_btn.setText("Copiar informe"))
