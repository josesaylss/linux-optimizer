"""Página de administración de servicios systemd."""

from __future__ import annotations

from PySide6.QtGui import QColor
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from linux_optimizer.core import services
from linux_optimizer.ui.widgets import (
    Card,
    confirm,
    error_dialog,
    info_dialog,
    run_worker,
)


class ServicesPage(QWidget):
    def __init__(self, backup_store, parent: QWidget | None = None):
        super().__init__(parent)
        self._backup = backup_store
        self._services: list[services.SystemdService] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 18, 24, 18)
        layout.setSpacing(12)

        title = QLabel("Servicios del sistema")
        title.setObjectName("headerTitle")
        layout.addWidget(title)
        subtitle = QLabel(
            "Los servicios esenciales (systemd, dbus, red, sesión gráfica…) están "
            "protegidos y no pueden detenerse ni deshabilitarse. Cada cambio crea "
            "un respaldo automático del estado previo."
        )
        subtitle.setObjectName("headerSubtitle")
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)

        filters = QHBoxLayout()
        self._search = QLineEdit()
        self._search.setPlaceholderText("Filtrar por nombre o descripción…")
        self._search.textChanged.connect(self._apply_filter)
        filters.addWidget(self._search, 1)
        self._show_essential = QPushButton("Ver esenciales")
        self._show_essential.setCheckable(True)
        self._show_essential.setChecked(True)
        self._show_essential.toggled.connect(self._apply_filter)
        filters.addWidget(self._show_essential)
        self._refresh_btn = QPushButton("Actualizar")
        self._refresh_btn.clicked.connect(self.refresh)
        filters.addWidget(self._refresh_btn)
        layout.addLayout(filters)

        table_card = Card()
        self._table = QTableWidget(0, 5)
        self._table.setHorizontalHeaderLabels(
            ["Servicio", "Descripción", "Estado", "Arranque", "Protegido"])
        self._table.verticalHeader().setVisible(False)
        self._table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectRows)
        self._table.setSelectionMode(QTableWidget.SingleSelection)
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        table_card.body.addWidget(self._table)
        layout.addWidget(table_card, 1)

        buttons = QHBoxLayout()
        self._start_btn = QPushButton("Iniciar")
        self._stop_btn = QPushButton("Detener")
        self._restart_btn = QPushButton("Reiniciar")
        self._enable_btn = QPushButton("Habilitar arranque")
        self._disable_btn = QPushButton("Deshabilitar arranque")
        self._restore_btn = QPushButton("Restaurar respaldo…")
        for b in (self._start_btn, self._stop_btn, self._restart_btn,
                  self._enable_btn, self._disable_btn):
            buttons.addWidget(b)
        buttons.addStretch(1)
        buttons.addWidget(self._restore_btn)
        layout.addLayout(buttons)

        self._start_btn.clicked.connect(lambda: self._action("start"))
        self._stop_btn.clicked.connect(lambda: self._action("stop"))
        self._restart_btn.clicked.connect(lambda: self._action("restart"))
        self._enable_btn.clicked.connect(lambda: self._action("enable"))
        self._disable_btn.clicked.connect(lambda: self._action("disable"))
        self._restore_btn.clicked.connect(self._restore_last)

        self.refresh()

    # ------------------------------------------------------------------
    # Carga de datos
    # ------------------------------------------------------------------

    def refresh(self) -> None:
        self._refresh_btn.setEnabled(False)
        self._refresh_btn.setText("Cargando…")

        def done(result):
            self._refresh_btn.setEnabled(True)
            self._refresh_btn.setText("Actualizar")
            self._services = result
            self._apply_filter()

        def error(message):
            self._refresh_btn.setEnabled(True)
            self._refresh_btn.setText("Actualizar")
            error_dialog(self, "Servicios", "No se pudo consultar systemd.", message)

        run_worker(self._refresh_btn, services.list_services, done, error,
                   "Cargando…", self)

    def _apply_filter(self) -> None:
        text = self._search.text().lower()
        show_essential = self._show_essential.isChecked()
        self._table.setRowCount(0)
        for service in self._services:
            if not show_essential and service.essential:
                continue
            if text and text not in service.unit.lower() \
                    and text not in service.description.lower():
                continue
            row = self._table.rowCount()
            self._table.insertRow(row)
            self._table.setItem(row, 0, QTableWidgetItem(service.unit))
            self._table.setItem(row, 1, QTableWidgetItem(service.description))
            state_item = QTableWidgetItem(service.active_state)
            state_item.setForeground(
                QColor("#58d68d") if service.running else QColor("#8b95ad"))
            self._table.setItem(row, 2, state_item)
            self._table.setItem(row, 3, QTableWidgetItem(service.enabled_state or "—"))
            essential_item = QTableWidgetItem("🔒 protegido" if service.essential else "")
            self._table.setItem(row, 4, essential_item)
        self._table.setColumnWidth(0, 260)
        self._table.setColumnWidth(2, 110)
        self._table.setColumnWidth(3, 110)
        self._table.setColumnWidth(4, 120)

    def _selected_service(self) -> services.SystemdService | None:
        rows = self._table.selectionModel().selectedRows() if self._table.selectionModel() else []
        if not rows:
            return None
        unit = self._table.item(rows[0].row(), 0).text()
        for service in self._services:
            if service.unit == unit:
                return service
        return None

    # ------------------------------------------------------------------
    # Acciones
    # ------------------------------------------------------------------

    def _action(self, action: str) -> None:
        service = self._selected_service()
        if not service:
            info_dialog(self, "Servicios", "Selecciona un servicio en la tabla.")
            return
        reason = services.action_blocked_reason(service.unit, action)
        if reason:
            info_dialog(self, "Acción no permitida", reason)
            return

        verb = {
            "start": "iniciar", "stop": "detener", "restart": "reiniciar",
            "enable": "habilitar en el arranque", "disable": "deshabilitar del arranque",
        }[action]
        detail = (
            f"Servicio: {service.unit}\n"
            f"Estado actual: {service.active_state} / {service.enabled_state}\n\n"
            "• Se guardará un respaldo del estado previo.\n"
            "• Se pedirá tu contraseña (pkexec).\n"
            "• Podrás restaurar el estado anterior con «Restaurar respaldo…»."
        )
        if not confirm(self, f"¿{verb.capitalize()} {service.unit}?",
                       f"Vas a {verb} el servicio {service.unit}.", detail=detail):
            return

        button = self._sender()
        button.setEnabled(False)

        def done(result):
            button.setEnabled(True)
            ok, message = result
            if ok:
                info_dialog(self, "Servicios", f"✔ {message}")
            else:
                error_dialog(self, "Servicios", f"No se pudo {verb} {service.unit}.", message)
            self.refresh()

        def error(message):
            button.setEnabled(True)
            error_dialog(self, "Servicios", "Error inesperado.", message)

        run_worker(button, lambda: services.apply_action(self._backup, service.unit, action),
                   done, error, "Ejecutando…", self)

    def _restore_last(self) -> None:
        snapshots = self._backup.list_snapshots(services.SERVICES_BACKUP_KIND)
        if not snapshots:
            info_dialog(self, "Restaurar", "Todavía no hay respaldos de servicios.")
            return
        lines = "\n".join(f"• {s['label']} ({s['created']})" for s in snapshots[:5])
        if not confirm(self, "Restaurar respaldo",
                       "Se restaurará el último respaldo de servicios:\n\n"
                       + lines.split("\n")[0],
                       detail=lines, danger=True):
            return
        self._restore_btn.setEnabled(False)

        def done(result):
            self._restore_btn.setEnabled(True)
            ok, message = result
            if ok:
                info_dialog(self, "Restaurar", f"✔ {message}")
            else:
                error_dialog(self, "Restaurar", "No se pudo restaurar.", message)
            self.refresh()

        def error(message):
            self._restore_btn.setEnabled(True)
            error_dialog(self, "Restaurar", "Error inesperado.", message)

        latest = snapshots[0]
        run_worker(self._restore_btn,
                   lambda: services.restore_service_state(self._backup, latest["id"]),
                   done, error, "Restaurando…", self)
