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
from linux_optimizer.core.globalfps import global_fps_enabled, set_global_fps
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
        self._test_closing = False
        if hud is not None:
            closed = getattr(hud, "hidden", None)
            if closed is not None:
                closed.connect(self._on_hud_closed)
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

        # Acciones rápidas visibles sin desplazar la página.
        quick = QHBoxLayout()
        self._hud_btn = QPushButton("Mostrar HUD")
        self._hud_btn.setCheckable(True)
        self._hud_btn.setEnabled(self._hud is not None)
        self._hud_btn.toggled.connect(self._toggle_hud)
        quick.addWidget(self._hud_btn)
        self._fps_test_btn = QPushButton("Probar FPS")
        self._fps_test_btn.setToolTip(
            "Abre el HUD y lanza glxgears con MangoHud para comprobar que los FPS "
            "llegan en tiempo real."
        )
        self._fps_test_btn.clicked.connect(self._test_fps)
        self._fps_test_btn.setEnabled(self._fps_pipeline_available())
        quick.addWidget(self._fps_test_btn)
        quick.addStretch(1)
        layout.addLayout(quick)

        # Controles de FPS y HUD visibles sin desplazar la página.
        self._hud_game_auto = QCheckBox(
            "Mostrar el HUD automáticamente al abrir un juego o app")
        self._hud_game_auto.setChecked(
            bool(getattr(self._hud, "auto_enabled", False)))
        self._hud_game_auto.setEnabled(
            self._hud is not None and hasattr(self._hud, "set_auto_enabled"))
        self._hud_game_auto.toggled.connect(self._set_hud_auto_show)
        layout.addWidget(self._hud_game_auto)

        self._global_fps = QCheckBox(
            "Capturar FPS en todos los juegos y apps (MangoHud global)")
        self._global_fps.setChecked(global_fps_enabled())
        self._global_fps.toggled.connect(self._toggle_global_fps)
        layout.addWidget(self._global_fps)

        self._global_note = QLabel(self._global_fps_status())
        self._global_note.setObjectName("headerSubtitle")
        self._global_note.setWordWrap(True)
        layout.addWidget(self._global_note)

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
        import logging

        from PySide6.QtCore import QProcess, QProcessEnvironment, QTimer

        log = logging.getLogger("LinuxOptimizer.gaming")

        if self._hud is not None and not self._hud_btn.isChecked():
            # Mantiene el botón de la página sincronizado con el HUD.
            self._hud_btn.setChecked(True)
        log_dir = ensure_mangolog_dir()
        cfg = f"output_folder={log_dir},autostart_log=1,log_interval=0"

        proc = QProcess(self)
        proc.setProcessChannelMode(QProcess.ProcessChannelMode.SeparateChannels)
        env = QProcessEnvironment.systemEnvironment()
        env.insert("MANGOHUD_CONFIG", cfg)
        proc.setProcessEnvironment(env)
        self._test_closing = False

        def log_stderr() -> None:
            raw = bytes(proc.readAllStandardError()).decode("utf-8", "replace")
            if raw.strip():
                log.info("Prueba FPS stderr: %s", raw.strip()[:1500])

        def on_error(error) -> None:
            log.warning("Prueba FPS error QProcess: %s", error)
            self._fps_test_btn.setEnabled(True)
            if self._test_closing:
                return
            error_dialog(
                self, "Prueba de FPS",
                "No se pudo lanzar «mangohud glxgears». Comprueba que MangoHud "
                "y glxgears estén instalados.",
            )

        def on_finished(code, status) -> None:
            log_stderr()
            log.info("Prueba FPS terminada: code=%s status=%s", code, status)
            self._fps_test_btn.setEnabled(True)

        def check_csv() -> None:
            logs = sorted(log_dir.glob("*.csv"))
            log.info("Prueba FPS: CSV encontrados=%d (%s)",
                     len(logs), [p.name for p in logs[-2:]])
            if not logs:
                self._status.setText(
                    "⚠ La prueba no generó registro de FPS. Revisa el aviso de abajo."
                )

        proc.readyReadStandardError.connect(log_stderr)
        proc.finished.connect(on_finished)
        proc.errorOccurred.connect(on_error)

        self._fps_test_btn.setEnabled(False)
        self._status.setText(
            "Prueba de FPS en curso: deberías ver ~60 FPS en el HUD."
        )
        log.info("Prueba FPS: ejecutando mangohud glxgears con MANGOHUD_CONFIG=%s", cfg)
        proc.start("mangohud", ["glxgears"])
        if not proc.waitForStarted(3000):
            log.warning("Prueba FPS: no arrancó (%s)", proc.errorString())
            self._fps_test_btn.setEnabled(True)
            error_dialog(self, "Prueba de FPS",
                         f"No se pudo iniciar MangoHud: {proc.errorString()}")
            return
        # Deja correr la prueba 15 s y luego la cierra sola.
        QTimer.singleShot(4000, check_csv)
        QTimer.singleShot(15000, lambda: self._stop_test(proc))

    def _stop_test(self, proc) -> None:
        """Cierra el programa de prueba si sigue ejecutándose."""
        from PySide6.QtCore import QProcess

        try:
            if proc is None or proc.state() == QProcess.ProcessState.NotRunning:
                return
            self._test_closing = True
            proc.terminate()
            if not proc.waitForFinished(2000):
                proc.kill()
        finally:
            self._fps_test_btn.setEnabled(True)

    def _fps_hint_text(self) -> str:
        import shutil
        log_dir = ensure_mangolog_dir()
        if not shutil.which("mangohud"):
            return ("MangoHud no está instalado; sin él no se pueden leer los FPS. "
                    "Instala el paquete «mangohud» (o su versión Flatpak) y vuelve a abrir "
                    "esta página.")
        return (
            "El HUD lee los FPS del registro de MangoHud y detecta el juego solo.\n\n"
            "✔ Lo más fácil: activa la casilla de abajo y reinicia la sesión una vez. "
            "Todos los juegos y apps Vulkan (incluidos Proton/DXVK) registrarán FPS "
            "sin configurar nada más.\n\n"
            "Alternativa por juego (también sirve para OpenGL):\n"
            f"    MANGOHUD_CONFIG=output_folder={log_dir},autostart_log=1,log_interval=0 "
            "mangohud <comando>\n"
            "⚠ «autostart_log=1» es obligatorio: con 0 MangoHud no escribe el registro.\n"
            "Con gamescope:  gamescope --mangoapp -- <juego>\n\n"
            "Para ver el HUD sobre un juego a pantalla completa usa el modo «ventana "
            "sin bordes»: en GNOME/Wayland una ventana normal no puede dibujarse "
            "encima de la pantalla completa exclusiva."
        )

    def _global_fps_status(self) -> str:
        if global_fps_enabled():
            return ("✔ Captura global activada. Se aplicará a todos los juegos "
                    "Vulkan/Proton la próxima vez que inicies sesión (cierra sesión "
                    "y vuelve a entrar). Si el juego es OpenGL, lánzalo con «mangohud».")
        return ("Desactivada: solo se registran los FPS de los juegos que lances a "
                "mano con «mangohud». Actívala para que funcione con todos "
                "automáticamente.")

    def _toggle_global_fps(self, on: bool) -> None:
        import logging
        log = logging.getLogger("LinuxOptimizer.gaming")
        try:
            path = set_global_fps(on)
        except OSError as exc:
            self._global_fps.blockSignals(True)
            self._global_fps.setChecked(not on)
            self._global_fps.blockSignals(False)
            error_dialog(
                self, "Captura global de FPS",
                f"No se pudo escribir la configuración:\n{exc}",
            )
            return
        log.info("FPS global %s (%s)", "activado" if on else "desactivado", path)
        self._global_note.setText(self._global_fps_status())
        self._status.setText(
            "Captura global activada: reinicia la sesión para aplicarla."
            if on else "Captura global desactivada.")

    def _toggle_hud(self, on: bool) -> None:
        if self._hud is None:
            return
        if on:
            self._hud.show()
        else:
            self._hud.hide()

    def _set_hud_auto_show(self, on: bool) -> None:
        setter = getattr(self._hud, "set_auto_enabled", None)
        if setter is not None:
            setter(on)

    def _on_hud_closed(self) -> None:
        """El HUD se cerró con su ✕: desmarcar el botón de la página."""
        if self._hud_btn.isChecked():
            self._hud_btn.setChecked(False)

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
