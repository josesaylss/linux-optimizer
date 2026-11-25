"""Página de limpieza segura con confirmación explícita."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from linux_optimizer.core import cleaner
from linux_optimizer.core import platform_info
from linux_optimizer.core.cleaner import build_targets
from linux_optimizer.ui.widgets import (
    Card,
    confirm,
    error_dialog,
    fmt_bytes,
    info_dialog,
    run_worker,
)


class CleanerPage(QWidget):
    def __init__(self, distro_info, parent: QWidget | None = None):
        super().__init__(parent)
        self._targets = build_targets(distro_info.family)
        self._scan_results: dict[str, object] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 18, 24, 18)
        layout.setSpacing(12)

        title = QLabel("Limpieza segura")
        title.setObjectName("headerTitle")
        layout.addWidget(title)
        subtitle = QLabel(
            ("Cada objetivo solo borra datos regenerables de Windows. Las "
             "acciones de sistema piden tu confirmación."
             if platform_info.IS_WINDOWS else
             "Cada objetivo solo borra datos regenerables. Las acciones de "
             "sistema requieren tu confirmación y privilegios (pkexec).")
        )
        subtitle.setObjectName("headerSubtitle")
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)

        table_card = Card()
        self._table = QTableWidget(0, 5)
        self._table.setHorizontalHeaderLabels(
            ["", "Objetivo", "Descripción", "Tamaño", "Archivos"])
        self._table.verticalHeader().setVisible(False)
        self._table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectRows)
        self._table.setSelectionMode(QTableWidget.NoSelection)
        self._table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.Stretch)
        self._table.setAlternatingRowColors(True)
        table_card.body.addWidget(self._table)
        layout.addWidget(table_card, 1)

        self._status = QLabel("Pulsa «Escanear» para calcular el espacio liberable.")
        self._status.setObjectName("headerSubtitle")
        layout.addWidget(self._status)

        buttons = QHBoxLayout()
        self._scan_btn = QPushButton("Escanear")
        buttons.addWidget(self._scan_btn)
        buttons.addStretch(1)
        self._select_btn = QPushButton("Seleccionar todo")
        buttons.addWidget(self._select_btn)
        self._clean_btn = QPushButton("Limpiar selección")
        self._clean_btn.setObjectName("primary")
        buttons.addWidget(self._clean_btn)
        layout.addLayout(buttons)

        self._fill_table()
        self._scan_btn.clicked.connect(self.scan_all)
        self._select_btn.clicked.connect(self._select_all)
        self._clean_btn.clicked.connect(self.clean_selected)

    # ------------------------------------------------------------------
    # Tabla
    # ------------------------------------------------------------------

    def _fill_table(self) -> None:
        self._table.setRowCount(len(self._targets))
        for row, target in enumerate(self._targets):
            check_item = QTableWidgetItem()
            check_item.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
            check_item.setCheckState(Qt.CheckState.Unchecked)
            self._table.setItem(row, 0, check_item)

            scope = "🔒 sistema" if target.needs_root else "usuario"
            self._table.setItem(row, 1, QTableWidgetItem(f"{target.title}\n{scope}"))
            self._table.setItem(row, 2, QTableWidgetItem(target.description))
            self._table.setItem(row, 3, QTableWidgetItem("—"))
            self._table.setItem(row, 4, QTableWidgetItem("—"))
        self._table.setColumnWidth(0, 30)
        self._table.setColumnWidth(1, 240)
        self._table.setColumnWidth(3, 110)
        self._table.setColumnWidth(4, 90)

    def _checked_rows(self) -> list[int]:
        rows = []
        for row in range(self._table.rowCount()):
            item = self._table.item(row, 0)
            if item and item.checkState() == Qt.CheckState.Checked:
                rows.append(row)
        return rows

    def _select_all(self) -> None:
        state = Qt.CheckState.Checked if self._checked_rows() != list(range(len(self._targets))) \
            else Qt.CheckState.Unchecked
        for row in range(self._table.rowCount()):
            self._table.item(row, 0).setCheckState(state)

    # ------------------------------------------------------------------
    # Escaneo
    # ------------------------------------------------------------------

    def scan_all(self) -> None:
        self._scan_btn.setEnabled(False)
        self._scan_btn.setText("Escaneando…")
        self._status.setText("Calculando tamaños, puede tardar unos segundos…")

        def work():
            results = {}
            for target in self._targets:
                if target.scan:
                    results[target.key] = target.scan()
            return results

        def done(results):
            self._scan_btn.setEnabled(True)
            self._scan_btn.setText("Escanear")
            self._scan_results = results
            total = 0
            for row, target in enumerate(self._targets):
                result = results.get(target.key)
                if result is None:
                    continue
                if getattr(result, "error", ""):
                    text = "error"
                elif getattr(result, "size", 0):
                    text = fmt_bytes(result.size)
                    total += result.size
                else:
                    text = getattr(result, "note", "") or "0 B"
                self._table.item(row, 3).setText(text)
                self._table.item(row, 4).setText(
                    f"{result.files:,}" if getattr(result, "files", 0) else "—")
            self._status.setText(
                f"Espacio potencialmente liberable: {fmt_bytes(total)}."
            )

        def error(message):
            self._scan_btn.setEnabled(True)
            self._scan_btn.setText("Escanear")
            self._status.setText("El escaneo falló.")
            error_dialog(self, "Escaneo", "No se pudo completar el escaneo.", message)

        run_worker(self._scan_btn, work, done, error, "Escaneando…", self)

    # ------------------------------------------------------------------
    # Limpieza
    # ------------------------------------------------------------------

    def clean_selected(self) -> None:
        rows = self._checked_rows()
        if not rows:
            info_dialog(self, "Limpieza", "Selecciona al menos un objetivo para limpiar.")
            return

        chosen = [self._targets[row] for row in rows]
        names = "\n".join(
            f"• {t.title}  {'(sistema, requiere contraseña)' if t.needs_root else ''}"
            for t in chosen
        )
        has_root = any(t.needs_root for t in chosen)
        root_note = (
            "\n\n🔒 Se pedirá tu contraseña UNA sola vez para todos los objetivos de sistema."
            if has_root else ""
        )
        confirmed = confirm(
            self,
            "Confirmar limpieza",
            f"Se eliminarán los datos temporales de:\n\n{names}\n\n"
            "Esta operación no se puede deshacer (los datos borrados no se respaldan)."
            + root_note,
            danger=True,
        )
        if not confirmed:
            return

        self._clean_btn.setEnabled(False)
        self._clean_btn.setText("Limpiando…")

        def work():
            return cleaner.clean_batch(chosen)

        def done(results):
            self._clean_btn.setEnabled(True)
            self._clean_btn.setText("Limpiar selección")
            freed = 0
            errors = []
            notes = []
            for key, result in results.items():
                title = next(
                    (t.title for t in self._targets if t.key == key), key)
                if getattr(result, "error", ""):
                    errors.append(f"{title}: {result.error}")
                else:
                    freed += getattr(result, "freed", 0)
                    note = getattr(result, "note", "")
                    if note:
                        notes.append(f"{title}: {note}")
            summary = f"Espacio liberado: {fmt_bytes(freed)}" if freed else "Limpieza completada."
            if notes:
                summary += "\n" + "\n".join(notes)
            self._status.setText(summary)
            if errors:
                error_dialog(self, "Limpieza",
                             "Algunos objetivos no se pudieron limpiar "
                             "(revisa el mensaje de cada uno):",
                             "\n".join(errors))
            self.scan_all()

        def error(message):
            self._clean_btn.setEnabled(True)
            self._clean_btn.setText("Limpiar selección")
            error_dialog(self, "Limpieza", "Error inesperado durante la limpieza.", message)

        run_worker(self._clean_btn, work, done, error, "Limpiando…", self)
