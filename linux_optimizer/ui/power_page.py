"""Página de administración de energía."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from linux_optimizer.core import power
from linux_optimizer.ui.widgets import (
    Card,
    SectionTitle,
    confirm,
    error_dialog,
    fmt_bytes,
    info_dialog,
    run_worker,
)


class PowerPage(QWidget):
    def __init__(self, backup_store, parent: QWidget | None = None):
        super().__init__(parent)
        self._backup = backup_store
        self._backend: power.PowerBackend | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 18, 24, 18)
        layout.setSpacing(12)

        title = QLabel("Administración de energía")
        title.setObjectName("headerTitle")
        layout.addWidget(title)
        subtitle = QLabel(
            "Detecta el backend disponible en tu distribución "
            "(power-profiles-daemon, tuned o governor de CPU) y permite cambiar el "
            "perfil con confirmación y respaldo previo."
        )
        subtitle.setObjectName("headerSubtitle")
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)

        backend_card = Card()
        backend_card.body.addWidget(SectionTitle("Perfil de energía"))
        self._backend_label = QLabel("Detectando…")
        backend_card.body.addWidget(self._backend_label)
        self._profiles_layout = QVBoxLayout()
        backend_card.body.addLayout(self._profiles_layout)
        self._radios: dict[str, QRadioButton] = {}

        apply_row = QHBoxLayout()
        apply_row.addStretch(1)
        self._restore_btn = QPushButton("Restaurar perfil anterior")
        apply_row.addWidget(self._restore_btn)
        self._apply_btn = QPushButton("Aplicar perfil")
        self._apply_btn.setObjectName("primary")
        apply_row.addWidget(self._apply_btn)
        backend_card.body.addLayout(apply_row)
        layout.addWidget(backend_card)

        battery_card = Card()
        battery_card.body.addWidget(SectionTitle("Batería"))
        self._battery_label = QLabel("—")
        battery_card.body.addWidget(self._battery_label)
        layout.addWidget(battery_card)

        self._status = QLabel("")
        self._status.setObjectName("headerSubtitle")
        layout.addWidget(self._status)

        self._refresh_btn = QPushButton("Re-detectar backend")
        self._refresh_btn.clicked.connect(self.refresh)
        layout.addWidget(self._refresh_btn)
        layout.addStretch(1)

        self._apply_btn.clicked.connect(self.apply)
        self._restore_btn.clicked.connect(self.restore)
        self.refresh()

    # ------------------------------------------------------------------

    def refresh(self) -> None:
        self._refresh_btn.setEnabled(False)

        def done(result):
            self._refresh_btn.setEnabled(True)
            self._backend = result
            self._render()

        def error(message):
            self._refresh_btn.setEnabled(True)
            self._backend_label.setText("No se pudo detectar el backend.")
            error_dialog(self, "Energía", "Error al detectar el backend.", message)

        run_worker(self._refresh_btn, power.detect_backend, done, error,
                   "Detectando…", self)
        self._update_battery()

    def _render(self) -> None:
        for radio in self._radios.values():
            radio.deleteLater()
        self._radios.clear()
        backend = self._backend
        if backend is None:
            return
        if not backend.available:
            self._backend_label.setText(
                f"⚠ Backend: {backend.name}. No hay perfiles disponibles.")
            self._apply_btn.setEnabled(False)
            self._restore_btn.setEnabled(False)
            return
        self._backend_label.setText(f"Backend detectado: {backend.name}")
        self._apply_btn.setEnabled(True)
        self._restore_btn.setEnabled(True)
        for profile in backend.profiles:
            radio = QRadioButton(profile + ("  (actual)" if profile == backend.current else ""))
            radio.setChecked(profile == backend.current)
            self._profiles_layout.addWidget(radio)
            self._radios[profile] = radio

    def _update_battery(self) -> None:
        battery = power.battery_info()
        if not battery:
            self._battery_label.setText("No se detectó batería (equipo de escritorio).")
            return
        plugged = "enchufado" if battery["plugged"] else "con batería"
        secs = battery["secs_left"]
        remaining = ""
        if secs and 0 < secs < 10**7:
            hours, rem = divmod(int(secs), 3600)
            remaining = f" · ~{hours}h {rem // 60}m restantes"
        self._battery_label.setText(
            f"Nivel: {battery['percent']}% ({plugged}){remaining}")

    # ------------------------------------------------------------------

    def _selected_profile(self) -> str | None:
        for profile, radio in self._radios.items():
            if radio.isChecked():
                return profile
        return None

    def apply(self) -> None:
        backend = self._backend
        profile = self._selected_profile()
        if backend is None or not backend.available or not profile:
            info_dialog(self, "Energía", "Selecciona un perfil disponible.")
            return
        if profile == backend.current:
            info_dialog(self, "Energia", f"El perfil «{profile}» ya está activo.")
            return
        if not confirm(
            self,
            "Confirmar cambio de perfil",
            f"¿Aplicar el perfil de energía «{profile}»?\n\n"
            "• Se guardará un respaldo del perfil anterior.\n"
            "• Se pedirá tu contraseña (pkexec).",
        ):
            return
        self._apply_btn.setEnabled(False)
        self._apply_btn.setText("Aplicando…")

        def done(result):
            self._apply_btn.setEnabled(True)
            self._apply_btn.setText("Aplicar perfil")
            ok, message = result
            if ok:
                self._status.setText(f"✔ {message}")
            else:
                error_dialog(self, "Energía", f"No se pudo aplicar «{profile}».", message)
            self.refresh()

        def error(message):
            self._apply_btn.setEnabled(True)
            self._apply_btn.setText("Aplicar perfil")
            error_dialog(self, "Energía", "Error inesperado.", message)

        run_worker(self._apply_btn,
                   lambda: power.set_profile(self._backup, backend, profile),
                   done, error, "Aplicando…", self)

    def restore(self) -> None:
        self._restore_btn.setEnabled(False)

        def done(result):
            self._restore_btn.setEnabled(True)
            ok, message = result
            if ok:
                self._status.setText(f"✔ {message}")
            else:
                info_dialog(self, "Restaurar", message)
            self.refresh()

        def error(message):
            self._restore_btn.setEnabled(True)
            error_dialog(self, "Restaurar", "Error inesperado.", message)

        run_worker(self._restore_btn,
                   lambda: power.restore_last_power_profile(self._backup),
                   done, error, "Restaurando…", self)
