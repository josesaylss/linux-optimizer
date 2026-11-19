"""Página del Modo Gaming."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from linux_optimizer.core.gaming import GamingManager
from linux_optimizer.core.gamehud import ensure_mangolog_dir
from linux_optimizer.ui.widgets import (
    Card,
    SectionTitle,
    confirm,
    error_dialog,
    info_dialog,
    run_worker,
)


class GamingPage(QWidget):
    def __init__(self, gaming_manager: GamingManager, hud=None, parent: QWidget | None = None):
        super().__init__(parent)
        self._manager = gaming_manager
        self._hud = hud
        # Carpeta donde MangoHud escribirá los FPS en vivo (si no existe).
        try:
            ensure_mangolog_dir()
        except OSError:
            pass

        # Contenido desplazable: si la ventana es baja, se hace scroll en vez
        # de comprimir las casillas a altura 0 (bug visto en Wayland).
        content = QWidget()
        layout = QVBoxLayout(content)
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
            box.setMinimumHeight(26)
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
        self._hud_btn = QPushButton("Mostrar HUD")
        self._hud_btn.setCheckable(True)
        self._hud_btn.setEnabled(self._hud is not None)
        self._hud_btn.toggled.connect(self._toggle_hud)
        buttons.addWidget(self._hud_btn)
        buttons.addStretch(1)
        self._revert_btn = QPushButton("Salir del modo gaming")
        buttons.addWidget(self._revert_btn)
        self._apply_btn = QPushButton("Activar modo gaming")
        self._apply_btn.setObjectName("primary")
        buttons.addWidget(self._apply_btn)
        layout.addLayout(buttons)

        self._apply_btn.clicked.connect(self.apply)
        self._revert_btn.clicked.connect(self.revert)

        # Casilla: mostrar HUD automáticamente al activar el modo.
        self._hud_auto = QCheckBox("Mostrar el HUD de rendimiento al activar")
        self._hud_auto.setChecked(True)
        self._hud_auto.setEnabled(self._hud is not None)
        layout.addWidget(self._hud_auto)

        # Guía de FPS con MangoHud
        fps_card = Card()
        fps_card.body.addWidget(SectionTitle("FPS en vivo (MangoHud)"))
        fps_hint = QLabel(self._fps_hint_text())
        fps_hint.setObjectName("headerSubtitle")
        fps_hint.setWordWrap(True)
        fps_card.body.addWidget(fps_hint)
        self._fps_test_btn = QPushButton("Probar FPS ahora (glxgears)")
        self._fps_test_btn.setToolTip(
            "Abre el HUD y lanza glxgears con MangoHud para comprobar que los FPS "
            "llegan en tiempo real."
        )
        self._fps_test_btn.clicked.connect(self._test_fps)
        self._fps_test_btn.setEnabled(self._fps_pipeline_available())
        fps_card.body.addWidget(self._fps_test_btn)
        layout.addWidget(fps_card)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(content)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

    def _fps_pipeline_available(self) -> bool:
        import shutil
        return bool(shutil.which("mangohud") and shutil.which("glxgears"))

    def _test_fps(self) -> None:
        """Lanza un programa de prueba con MangoHud para verificar los FPS."""
        from PySide6.QtCore import QProcess, QProcessEnvironment

        if self._hud is not None:
            self._hud.show()
        log_dir = ensure_mangolog_dir()
        proc = QProcess(self)
        env = QProcessEnvironment.systemEnvironment()
        env.insert(
            "MANGOHUD_CONFIG",
            f"output_folder={log_dir},autostart_log=1,log_interval=0",
        )
        proc.setProcessEnvironment(env)
        proc.finished.connect(lambda *_: self._fps_test_btn.setEnabled(True))
        proc.errorOccurred.connect(
            lambda *_: (
                self._fps_test_btn.setEnabled(True),
                error_dialog(
                    self,
                    "Prueba de FPS",
                    "No se pudo lanzar «mangohud glxgears». Comprueba que MangoHud "
                    "y glxgears estén instalados.",
                ),
            )
        )
        self._fps_test_btn.setEnabled(False)
        self._status.setText(
            "Prueba de FPS en curso: deberías ver ~60 FPS en el HUD."
        )
        proc.start("mangohud", ["glxgears"])

    def _fps_hint_text(self) -> str:
        import shutil
        log_dir = ensure_mangolog_dir()
        if shutil.which("mangohud"):
            return (
                "✔ MangoHud instalado. Para que este HUD muestre los FPS en tiempo real, "
                "lanza el juego con el registro de métricas activado:\n\n"
                "• Steam → Propiedades → Opciones de lanzamiento:\n"
                f"    MANGOHUD_CONFIG=output_folder={log_dir},autostart_log=1,log_interval=0 "
                "mangohud %command%\n"
                "• Terminal:\n"
                f"    MANGOHUD_CONFIG=output_folder={log_dir},autostart_log=1,log_interval=0 "
                "mangohud <comando-del-juego>\n\n"
                "⚠ «autostart_log=1» es obligatorio: con 0 MangoHud no escribe el "
                "registro y el HUD no puede leer los FPS.\n"
                "Con gamescope también funciona:  gamescope --mangoapp -- <juego>\n"
                "El HUD detecta el juego automáticamente y actualiza los FPS 2 veces por segundo."
            )
        return ("MangoHud no está instalado; sin él no se pueden leer los FPS del juego. "
                "Instala el paquete «mangohud» y lanza el juego con «mangohud %command%» en Steam.")

    def _toggle_hud(self, on: bool) -> None:
        if self._hud is None:
            return
        if on:
            self._hud.show()
        else:
            self._hud.hide()

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
            + ("\n\n🔒 Se pedirá tu contraseña UNA sola vez para todas las "
               "acciones de sistema, y se guardará un respaldo previo."
               if root_actions else "")
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
            if ok and self._hud is not None and self._hud_auto.isChecked():
                self._hud.show()
                self._hud_btn.setChecked(True)
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
