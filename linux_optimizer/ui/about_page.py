"""Página «Acerca de»: información del entorno e historial de respaldos."""

from __future__ import annotations

import platform

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from linux_optimizer import APP_NAME, __version__
from linux_optimizer.core.backup import BackupStore
from linux_optimizer.ui.widgets import (
    Card,
    SectionTitle,
    confirm,
    error_dialog,
    info_dialog,
)

_KIND_NAMES = {
    "services": "⚙️ Servicios",
    "power": "🔋 Energía",
    "gaming": "🎮 Modo gaming",
    "kernel": "🧩 Swappiness",
}


class AboutPage(QWidget):
    def __init__(self, backup_store: BackupStore, distro_info, parent: QWidget | None = None):
        super().__init__(parent)
        self._backup = backup_store

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 18, 24, 18)
        layout.setSpacing(12)

        title = QLabel("Acerca de")
        title.setObjectName("headerTitle")
        layout.addWidget(title)

        info_card = Card()
        info_card.body.addWidget(SectionTitle("Aplicación"))
        self._info_label = QLabel(self._build_info_text(distro_info))
        info_card.body.addWidget(self._info_label)
        layout.addWidget(info_card)

        backups_card = Card()
        backups_card.body.addWidget(SectionTitle("Historial de respaldos"))
        self._table = QTableWidget(0, 3)
        self._table.setHorizontalHeaderLabels(["Fecha", "Tipo", "Etiqueta"])
        self._table.verticalHeader().setVisible(False)
        self._table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectRows)
        self._table.setSelectionMode(QTableWidget.SingleSelection)
        self._table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        backups_card.body.addWidget(self._table)
        layout.addWidget(backups_card, 1)

        buttons = QHBoxLayout()
        self._refresh_btn = QPushButton("Actualizar")
        self._refresh_btn.clicked.connect(self.refresh_backups)
        buttons.addWidget(self._refresh_btn)
        self._open_btn = QPushButton("Abrir carpeta de respaldos")
        self._open_btn.clicked.connect(self._open_folder)
        buttons.addWidget(self._open_btn)
        buttons.addStretch(1)
        self._delete_btn = QPushButton("Eliminar seleccionado")
        self._delete_btn.clicked.connect(self._delete_selected)
        buttons.addWidget(self._delete_btn)
        layout.addLayout(buttons)

        self.refresh_backups()

    # ------------------------------------------------------------------

    def _build_info_text(self, distro_info) -> str:
        import PySide6
        return "\n".join([
            f"{APP_NAME} {__version__} — herramienta gráfica de optimización para Linux.",
            "",
            f"Distribución: {distro_info.pretty}",
            f"Kernel: {platform.release()} ({platform.machine()})",
            f"Python: {platform.python_version()}  ·  PySide6/Qt: {PySide6.__version__}",
            "",
            "Seguridad: confirmación antes de cada cambio, elevación solo con pkexec,",
            "respaldos automáticos previos y servicios esenciales protegidos.",
        ])

    def refresh_backups(self) -> None:
        snapshots = self._backup.list_snapshots()
        self._table.setRowCount(0)
        for snap in snapshots:
            row = self._table.rowCount()
            self._table.insertRow(row)
            self._table.setItem(row, 0, QTableWidgetItem(snap.get("created", "")))
            kind = _KIND_NAMES.get(snap.get("kind", ""), snap.get("kind", "?"))
            self._table.setItem(row, 1, QTableWidgetItem(kind))
            self._table.setItem(row, 2, QTableWidgetItem(snap.get("label", "")))
        self._table.setColumnWidth(0, 170)
        self._table.setColumnWidth(1, 150)

    def _selected_id(self) -> str | None:
        rows = self._table.selectionModel().selectedRows() if self._table.selectionModel() else []
        if not rows:
            return None
        snap_id = ""
        # El id no se muestra: se resuelve por fila contra el historial ordenado.
        snapshots = self._backup.list_snapshots()
        if rows[0].row() < len(snapshots):
            snap_id = snapshots[rows[0].row()]["id"]
        return snap_id or None

    def _open_folder(self) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self._backup.base_dir)))

    def _delete_selected(self) -> None:
        snap_id = self._selected_id()
        if not snap_id:
            info_dialog(self, "Respaldos", "Selecciona un respaldo en la tabla.")
            return
        meta = self._backup.load(snap_id) or {}
        if not confirm(
            self,
            "Eliminar respaldo",
            f"¿Eliminar definitivamente el respaldo?\n\n"
            f"{meta.get('label', snap_id)}\n({meta.get('created', '')})",
            danger=True,
        ):
            return
        if self._backup.delete(snap_id):
            self.refresh_backups()
        else:
            error_dialog(self, "Respaldos", "No se pudo eliminar el respaldo.")
