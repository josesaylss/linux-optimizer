"""Página del Modo Gaming."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from linux_optimizer.core.gaming import GamingManager
from linux_optimizer.ui.widgets import (
    Card,
    SectionTitle,
    confirm,
    error_dialog,
    info_dialog,
    run_worker,
)


class GamingPage(QWidget):
    def __init__(self, gaming_manager: GamingManager, parent: QWidget | None = None):
        super().__init__(parent)
        self._manager = gaming_manager

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 18, 24, 18)
        layout.setSpacing(12)

        title = QLabel("Modo Gaming")
        title.setObjectName("headerTitle")
        layout.addWidget(title)
        subtitle = QLabel(
            "Optimizaciones temporales y reversibles. Cada cambio se guarda en un "
            "respaldo y se puede revertir con «Salir del modo gaming»."
        )
        subtitle.setObjectName("headerSubtitle")
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)

        hardware_info = Card()
        hardware_info.body.addWidget(SectionTitle("Hardware detectado"))
        self._hw_label = QLabel(gaming_manager.hardware_summary())
        hardware_info.body.addWidget(self._hw_label)
        self._gamemode_label = QLabel()
        self._refresh_gamemode()
        hardware_info.body.addWidget(self._gamemode_label)
        layout.addWidget(hardware_info)

        actions_card = Card()
        actions_card.body.addWidget(SectionTitle("Acciones disponibles"))
        self._checkboxes: dict[str, tuple[QCheckBox, GamingActionLike]] = {}
        for action in self._manager.actions:
            box = QCheckBox(
                f"{action.title}  {'🔒' if action.needs_root else ''}"
                + ("  (no compatible)" if not action.supported else "")
            )
            box.setEnabled(action.supported)
            if not action.supported:
                box.setToolTip(action.unsupported_reason)
                box.setChecked(False)
            box.setText(box.text())  # conserva el texto
            label = QLabel(action.description)
            label.setObjectName("headerSubtitle")
            label.setWordWrap(True)
            label.setIndent(26)
            if not action.supported:
                label.setText(f"{action.description}\n⚠ {action.unsupported_reason}")
            actions_card.body.addWidget(box)
            actions_card.body.addWidget(label)
            self._checkboxes[action.key] = (box, action)
        layout.addWidget(actions_card, 1)

        self._status = QLabel("El modo gaming está desactivado.")
        self._status.setObjectName("headerSubtitle")
        layout.addWidget(self._status)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self._revert_btn = QPushButton("Salir del modo gaming")
        buttons.addWidget(self._revert_btn)
        self._apply_btn = QPushButton("Activar modo gaming")
        self._apply_btn.setObjectName("primary")
        buttons.addWidget(self._apply_btn)
        layout.addLayout(buttons)

        self._apply_btn.clicked.connect(self.apply)
        self._revert_btn.clicked.connect(self.revert)

    def _refresh_gamemode(self) -> None:
        if self._manager.gamemode_installed():
            self._gamemode_label.setText("✔ GameMode (Feral) instalado: los juegos lo usarán automáticamente.")
        else:
            self._gamemode_label.setText(
                "ℹ GameMode (Feral) no está instalado. Puedes instalarlo con el gestor de "
                "paquetes (paquete «gamemode») para más rendimiento automáticamente."
            )

    # ------------------------------------------------------------------

    def apply(self) -> None:
        keys = [key for key, (box, _action) in self._checkboxes.items()
                if box.isEnabled() and box.isChecked()]
        if not keys:
            info_dialog(self, "Modo gaming", "Selecciona al menos una acción compatible.")
            return
        root_actions = [key for key in keys if self._checkboxes[key][1].needs_root]
        message = (
            "Se aplicarán las optimizaciones seleccionadas."
            + ("\n\nLas acciones marcadas con 🔒 pedirán tu contraseña (pkexec)." if root_actions else "")
            + "\n\nPodrás revertir todo con «Salir del modo gaming»."
        )
        if not confirm(self, "Confirmar modo gaming", message, danger=bool(root_actions)):
            return

        self._apply_btn.setEnabled(False)
        self._apply_btn.setText("Aplicando…")

        def done(result):
            self._apply_btn.setEnabled(True)
            self._apply_btn.setText("Activar modo gaming")
            ok, failed = result
            # Sincroniza casillas con el estado real de cada acción.
            for action in self._manager.actions:
                box = self._checkboxes[action.key][0]
                if action.supported:
                    box.setChecked(action.applied)
            self._status.setText(
                "✔ Modo gaming activo." if ok else "⚠ No se aplicó ningún cambio."
            )
            info_dialog(self, "Modo gaming", "Resultado:",
                        "\n".join(ok + failed) or "Sin cambios")

        def error(message):
            self._apply_btn.setEnabled(True)
            self._apply_btn.setText("Activar modo gaming")
            error_dialog(self, "Modo gaming", "Error inesperado.", message)

        run_worker(self._apply_btn, lambda: self._manager.apply(keys),
                   done, error, "Aplicando…", self)

    def revert(self) -> None:
        self._revert_btn.setEnabled(False)
        self._revert_btn.setText("Revirtiendo…")

        def done(result):
            self._revert_btn.setEnabled(True)
            self._revert_btn.setText("Salir del modo gaming")
            ok, failed = result
            self._status.setText("Modo gaming desactivado.")
            info_dialog(self, "Modo gaming", "Reversión completada:",
                        "\n".join(ok + failed) or "No había cambios que revertir")

        def error(message):
            self._revert_btn.setEnabled(True)
            self._revert_btn.setText("Salir del modo gaming")
            error_dialog(self, "Modo gaming", "Error inesperado.", message)

        run_worker(self._revert_btn, self._manager.revert_all,
                   done, error, "Revirtiendo…", self)


class GamingActionLike:  # solo para anotación
    pass
