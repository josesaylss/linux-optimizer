"""Páginas de la interfaz de Cortex Gaming Engine.

Cada pestaña es un módulo propio (panel, perfiles, CPU, GPU, RAM,
Game Booster, actividad y ajustes) de esta sesión de la misma aplicación.
No comparte estado con Linux Optimizer: solo reutiliza utilidades genéricas
de diálogos e hilos.
"""

from __future__ import annotations

import platform
from pathlib import Path

from PySide6.QtCore import QUrl, Qt, QTimer, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from cortex_engine import APP_NAME, APP_VERSION
from cortex_engine.config import config_path, state_dir
from cortex_engine.interface.widgets import (
    ActivityList,
    Card,
    KeyValueRow,
    MetricTile,
    Page,
    SectionTitle,
)
from cortex_engine.profiles.manager import PROFILE_MAP, PROFILES, apply_commands
from linux_optimizer.core import platform_info
from linux_optimizer.ui.widgets import (
    confirm,
    error_dialog,
    info_dialog,
    run_worker,
)


def _muted(text: str = "", wrap: bool = True) -> QLabel:
    label = QLabel(text)
    label.setObjectName("muted")
    label.setWordWrap(wrap)
    return label


def _row(*widgets: QWidget) -> QHBoxLayout:
    row = QHBoxLayout()
    row.setSpacing(12)
    for widget in widgets:
        row.addWidget(widget)
    return row


# ----------------------------------------------------------------------------
# Panel (monitorización propia)
# ----------------------------------------------------------------------------

class PanelPage(Page):
    """Vista general en vivo: CPU, GPU, RAM, temperatura y estado del motor."""

    def __init__(self, monitor, cpu, gpu, memory, profiles, activity,
                 parent: QWidget | None = None):
        super().__init__("Panel", "Monitorización propia de Cortex Gaming Engine",
                         parent)
        self.monitor = monitor
        self.cpu = cpu
        self.gpu = gpu
        self.memory = memory
        self.profiles = profiles
        self.activity = activity

        self._cpu_tile = MetricTile("CPU", show_bar=True)
        self._ram_tile = MetricTile("RAM", show_bar=True)
        self._gpu_tile = MetricTile("GPU", show_bar=True)
        self._temp_tile = MetricTile("TEMPERATURA", show_bar=True)
        row = _row(self._cpu_tile, self._ram_tile, self._gpu_tile,
                   self._temp_tile)
        wrapper = QWidget()
        wrapper.setLayout(row)
        self.body.addWidget(wrapper)

        status = Card()
        status.body.addWidget(SectionTitle("Estado del motor"))
        self._rows: dict[str, KeyValueRow] = {}
        grid = QGridLayout()
        grid.setHorizontalSpacing(26)
        grid.setVerticalSpacing(6)
        keys = [
            ("profile", "Perfil activo"),
            ("governor", "Plan de energía" if platform_info.IS_WINDOWS
             else "Governor de CPU"),
            ("epp", "Preferencia de energía"),
            ("gpu", "GPU detectada"),
            ("swappiness", "Swappiness"),
            ("snapshot", "Valores originales"),
        ]
        for index, (key, label) in enumerate(keys):
            row_widget = KeyValueRow(label)
            self._rows[key] = row_widget
            grid.addWidget(row_widget, index // 2, index % 2)
        status.body.addLayout(grid)
        self.body.addWidget(status)

        recent = Card()
        recent.body.addWidget(SectionTitle("Actividad reciente"))
        self._recent = QLabel("")
        self._recent.setObjectName("activityPreview")
        self._recent.setWordWrap(True)
        self._recent.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse)
        recent.body.addWidget(self._recent)
        self.body.addWidget(recent)
        self.body.addStretch(1)

        monitor.stats_updated.connect(self.update_stats)
        activity.changed.connect(self.refresh_activity)
        self.refresh_activity()
        self.refresh()

    # ------------------------------------------------------------------

    def update_stats(self, stats: dict) -> None:
        cpu = stats.get("cpu", {})
        ram = stats.get("ram", {})
        gpus = stats.get("gpus") or []

        cpu_pct = cpu.get("percent", 0.0)
        freq = cpu.get("freq_mhz", 0.0)
        load = cpu.get("load", [0, 0, 0])
        self._cpu_tile.set_value(
            f"{cpu_pct:.0f} %",
            f"{freq:.0f} MHz · {cpu.get('cores', '?')} núc. · "
            f"carga {load[0]:.2f}",
            percent=cpu_pct,
        )

        ram_pct = ram.get("percent", 0.0)
        self._ram_tile.set_value(
            f"{ram_pct:.0f} %",
            f"{ram.get('used_gb', 0):.1f} / {ram.get('total_gb', 0):.1f} GB · "
            f"swap {ram.get('swap_percent', 0):.0f} %",
            percent=ram_pct,
        )

        if gpus:
            gpu = gpus[0]
            util = gpu.get("util", 0.0)
            self._gpu_tile.set_value(
                f"{util:.0f} %",
                f"{gpu.get('name', 'GPU')} · "
                f"{gpu.get('mem_used_mb', 0):.0f}/"
                f"{gpu.get('mem_total_mb', 0):.0f} MB",
                percent=util,
            )
        else:
            self._gpu_tile.set_value("—", "Sin sensores de GPU", percent=None)

        temp = cpu.get("temp")
        if temp is None:
            self._temp_tile.set_value("—", "Sin sensor de CPU", percent=None)
        else:
            self._temp_tile.set_value(
                f"{temp:.0f} °C",
                f"{cpu.get('threads', 0)} hilos · "
                f"{stats.get('processes', 0)} procesos",
                percent=min(100.0, temp / 100.0),
            )

    def refresh_activity(self) -> None:
        entries = self.activity.entries()[-6:]
        self._recent.setText("\n".join(entries) or "Sin actividad registrada.")

    def refresh(self) -> None:
        active = self.profiles.active()
        self._rows["profile"].set_value(
            PROFILE_MAP[active].title if active else "Ninguno")
        state = self.cpu.state()
        self._rows["governor"].set_value(state.get("governor") or "—")
        self._rows["epp"].set_value(state.get("epp") or "no disponible")
        notes = self.gpu.notes()
        vendors = self.gpu.vendors()
        gpu_text = ", ".join(v.upper() for v in vendors) if vendors else "no detectada"
        if notes:
            gpu_text += " ⚠"
        self._rows["gpu"].set_value(gpu_text)
        swappiness = self.memory.state().get("swappiness")
        self._rows["swappiness"].set_value(
            str(swappiness) if swappiness is not None else "—")
        self._rows["snapshot"].set_value(
            "guardados" if self.profiles.has_snapshot() else "sin guardar")


# ----------------------------------------------------------------------------
# Perfiles
# ----------------------------------------------------------------------------

class ProfileCard(QFrame):
    apply_requested = Signal(str)

    def __init__(self, profile, preview: list[str],
                 parent: QWidget | None = None):
        super().__init__(parent)
        self.profile = profile
        self.setObjectName("profileCard")
        self.setProperty("active", "false")
        self.setMinimumWidth(220)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(8)

        name = QLabel(profile.title)
        name.setObjectName("profileName")
        name.setStyleSheet(f"color: {profile.accent};")
        layout.addWidget(name)

        tagline = QLabel(profile.tagline)
        tagline.setObjectName("profileTagline")
        layout.addWidget(tagline)

        desc = QLabel(profile.description)
        desc.setObjectName("profileDesc")
        desc.setWordWrap(True)
        layout.addWidget(desc)

        details = QLabel("\n".join(f"• {line}" for line in preview) or
                         "• Sin controles compatibles en este equipo")
        details.setObjectName("profileDesc")
        details.setWordWrap(True)
        layout.addWidget(details)
        layout.addStretch(1)

        self.button = QPushButton("Aplicar")
        self.button.setObjectName("accentButton")
        self.button.clicked.connect(
            lambda: self.apply_requested.emit(self.profile.key))
        layout.addWidget(self.button)

    def set_active(self, active: bool) -> None:
        self.setProperty("active", "true" if active else "false")
        self.button.setText("En uso" if active else "Aplicar")
        self.button.setEnabled(not active)
        self.style().unpolish(self)
        self.style().polish(self)


class ProfilesPage(Page):
    """Perfiles ECO, BALANCED y EXTREME aplicados en lote y reversibles."""

    def __init__(self, profiles, parent: QWidget | None = None):
        super().__init__(
            "Perfiles",
            "ECO, BALANCED y EXTREME · un solo paso por cambio · "
            "siempre reversible",
            parent,
        )
        self.profiles = profiles
        self._cards: dict[str, ProfileCard] = {}

        row = QHBoxLayout()
        row.setSpacing(12)
        for profile in PROFILES:
            card = ProfileCard(profile, profiles.preview(profile.key))
            card.apply_requested.connect(self.apply_profile)
            self._cards[profile.key] = card
            row.addWidget(card, 1)
        wrapper = QWidget()
        wrapper.setLayout(row)
        self.body.addWidget(wrapper)

        self._status = QLabel("")
        self._status.setObjectName("muted")
        self._status.setWordWrap(True)
        self.body.addWidget(self._status)

        restore = Card()
        restore.body.addWidget(SectionTitle("Restaurar el equipo"))
        self._snapshot = _muted(profiles.snapshot_info())
        restore.body.addWidget(self._snapshot)
        self._restore_btn = QPushButton("Restaurar valores originales")
        self._restore_btn.setObjectName("restoreButton")
        self._restore_btn.clicked.connect(self.restore)
        restore.body.addWidget(self._restore_btn)
        notes = profiles.notes("extreme")
        if notes:
            note = _muted("\n".join(notes))
            restore.body.addWidget(note)
        self.body.addWidget(restore)
        self.body.addStretch(1)

        profiles.changed.connect(self.refresh)
        self.refresh()

    # ------------------------------------------------------------------

    def refresh(self) -> None:
        active = self.profiles.active()
        for key, card in self._cards.items():
            card.set_active(key == active)
        self._snapshot.setText(self.profiles.snapshot_info())
        self._restore_btn.setText("Restaurar valores originales")
        self._restore_btn.setEnabled(self.profiles.has_snapshot())

    def apply_profile(self, key: str) -> None:
        profile = PROFILE_MAP.get(key)
        if profile is None:
            return
        preview = self.profiles.preview(key)
        if not preview:
            info_dialog(self, "Perfil no compatible",
                        "Este equipo no expone los controles que necesita "
                        f"el perfil {profile.title}.")
            return
        detail = (
            "Cortex guardará los valores originales antes de cambiar nada."
            if platform_info.IS_WINDOWS else
            "Cortex guardará los valores originales antes de cambiar nada y "
            "pedirá tu contraseña una sola vez.")
        if not confirm(
            self,
            f"Aplicar perfil {profile.title}",
            f"¿Aplicar el perfil {profile.title}?\n\n" + "\n".join(
                f"• {line}" for line in preview),
            danger=key == "extreme",
            detail=detail,
        ):
            return
        card = self._cards[key]
        run_worker(
            card.button,
            lambda: self.profiles.apply(key),
            self._on_applied,
            self._on_error,
            busy_text="Aplicando…",
            parent=self,
        )

    def _on_applied(self, result) -> None:
        ok, failed = result
        self.refresh()
        if failed:
            error_dialog(self, "Perfil aplicado parcialmente",
                         "Estos cambios no se pudieron aplicar:",
                         "\n".join(failed))
        else:
            self._status.setText(
                f"✔ {len(ok)} ajustes aplicados correctamente.")

    def restore(self) -> None:
        if not confirm(
            self,
            "Restaurar valores originales",
            ("Se devolverá el plan de energía del sistema al valor que había "
             "antes de optimizar con Cortex."
             if platform_info.IS_WINDOWS else
             "Se devolverán CPU, GPU y memoria a los valores que había antes "
             "de optimizar con Cortex."),
            detail=self.profiles.snapshot_info(),
        ):
            return
        run_worker(
            self._restore_btn,
            self.profiles.revert,
            self._on_restored,
            self._on_error,
            busy_text="Restaurando…",
            parent=self,
        )

    def _on_restored(self, result) -> None:
        ok, failed = result
        self.refresh()
        if failed:
            error_dialog(self, "Restauración incompleta",
                         "Algunos valores no se pudieron restaurar:",
                         "\n".join(failed))
        if ok:
            info_dialog(self, "Restauración completada",
                        f"Se restauraron {len(ok)} ajustes.")

    def _on_error(self, message: str) -> None:
        self.refresh()
        error_dialog(self, "Error de Cortex", message)


# ----------------------------------------------------------------------------
# CPU
# ----------------------------------------------------------------------------

class CpuPage(Page):
    def __init__(self, cpu, profiles, parent: QWidget | None = None):
        subtitle = ("Plan de energía de Windows"
                    if platform_info.IS_WINDOWS
                    else "Governor, preferencia de energía y turbo")
        super().__init__("CPU", subtitle, parent)
        self.cpu = cpu
        self.profiles = profiles
        self._windows = platform_info.IS_WINDOWS

        card = Card()
        card.body.addWidget(SectionTitle("Estado actual"))
        self._rows: dict[str, KeyValueRow] = {}
        for key, label in (
            ("model", "Procesador"),
            ("cpus", "CPU detectadas"),
            ("governor", "Plan de energía" if self._windows else "Governor"),
            ("epp", "Preferencia de energía"),
            ("boost", "Turbo / boost"),
            ("available", "Disponibles"),
        ):
            row = KeyValueRow(label)
            self._rows[key] = row
            card.body.addWidget(row)
        self.body.addWidget(card)

        per_profile = Card()
        per_profile.body.addWidget(SectionTitle("Qué aplica cada perfil"))
        self._profile_labels: dict[str, QLabel] = {}
        for profile in PROFILES:
            title = QLabel(profile.title)
            title.setStyleSheet(f"color: {profile.accent}; font-weight: 700;")
            per_profile.body.addWidget(title)
            lines = [label for _key, _cmd, label
                     in cpu.commands(profile.key)]
            body = _muted("\n".join(f"• {line}" for line in lines) or
                          "• Sin controles de CPU compatibles")
            self._profile_labels[profile.key] = body
            per_profile.body.addWidget(body)
        self.body.addWidget(per_profile)
        self.body.addStretch(1)
        profiles.changed.connect(self.refresh)
        self.refresh()

    def refresh(self) -> None:
        state = self.cpu.state()
        self._rows["model"].set_value(_cpu_model())
        self._rows["model"].value_label.setToolTip(_cpu_model())
        self._rows["cpus"].set_value(str(state.get("cpus", 0)))
        self._rows["governor"].set_value(state.get("governor") or "—")
        self._rows["epp"].set_value(
            state.get("epp") or ("no aplica" if self._windows
                                 else "no disponible"))
        self._rows["boost"].set_value(
            state.get("boost") or ("no aplica" if self._windows else "—"))
        if self._windows:
            self._rows["available"].set_value("planes de energía de Windows")
            return
        available = state.get("available_governors") or []
        epp = state.get("available_epp") or []
        full = ", ".join(available) + (f" · EPP: {', '.join(epp)}" if epp else "")
        short = full if len(full) <= 64 else full[:61] + "…"
        self._rows["available"].set_value(short or "—")
        self._rows["available"].value_label.setToolTip(full or "Sin datos")


def _cpu_model() -> str:
    if platform_info.IS_WINDOWS:
        return platform.processor() or platform.uname().processor or "CPU"
    try:
        with open("/proc/cpuinfo", encoding="utf-8") as fh:
            for line in fh:
                if line.lower().startswith("model name"):
                    return line.split(":", 1)[1].strip()
    except OSError:
        pass
    return "CPU del sistema"


# ----------------------------------------------------------------------------
# GPU
# ----------------------------------------------------------------------------

class GpuPage(Page):
    def __init__(self, gpu, parent: QWidget | None = None):
        super().__init__("GPU", "AMD, Intel y NVIDIA · sin forzar valores a ciegas",
                         parent)
        self.gpu = gpu

        card = Card()
        card.body.addWidget(SectionTitle("Estado actual"))
        self._rows: dict[str, KeyValueRow] = {}
        for key, label in (
            ("vendors", "Fabricantes detectados"),
            ("amd", "Tarjetas AMD"),
            ("intel", "Tarjetas Intel"),
            ("nvidia", "NVIDIA"),
        ):
            row = KeyValueRow(label)
            self._rows[key] = row
            card.body.addWidget(row)
        self.body.addWidget(card)

        state = gpu.state()
        self._rows["vendors"].set_value(
            ", ".join(v.upper() for v in state["vendors"]) or "no detectada")
        self._rows["amd"].set_value(str(len(state["amd"])))
        self._rows["intel"].set_value(str(len(state["intel"])))
        self._rows["nvidia"].set_value(
            "sí, gestionada por su driver"
            if "nvidia" in state["vendors"] else "no")

        notes = Card()
        notes.body.addWidget(SectionTitle("Avisos"))
        self._notes = _muted("\n".join(f"• {line}" for line in gpu.notes()) or
                             "• Sin avisos: se aplican solo controles seguros.")
        notes.body.addWidget(self._notes)
        self.body.addWidget(notes)
        self.body.addStretch(1)


# ----------------------------------------------------------------------------
# Memoria
# ----------------------------------------------------------------------------

class MemoryPage(Page):
    def __init__(self, memory, monitor, parent: QWidget | None = None):
        subtitle = ("Memoria y swap (Windows no expone swappiness)"
                    if platform_info.IS_WINDOWS
                    else "Swappiness, límites de mapas y cachés")
        super().__init__("RAM", subtitle, parent)
        self.memory = memory
        self.monitor = monitor
        self._cache_supported = bool(memory.drop_caches_commands())
        self._cache_label = ("Liberar cachés ahora (sync + drop_caches)"
                             if self._cache_supported
                             else "Liberar cachés no disponible en este sistema")

        tiles = QHBoxLayout()
        tiles.setSpacing(12)
        self._ram = MetricTile("MEMORIA", show_bar=True)
        self._swap = MetricTile("SWAP", show_bar=True)
        self._swappiness = MetricTile("SWAPPINESS")
        tiles.addWidget(self._ram, 1)
        tiles.addWidget(self._swap, 1)
        tiles.addWidget(self._swappiness, 1)
        wrapper = QWidget()
        wrapper.setLayout(tiles)
        self.body.addWidget(wrapper)

        card = Card()
        card.body.addWidget(SectionTitle("Límites del kernel"))
        self._rows: dict[str, KeyValueRow] = {}
        for key, label in (("max_map", "max_map_count"),
                           ("drop", "Liberar cachés")):
            row = KeyValueRow(label)
            self._rows[key] = row
            card.body.addWidget(row)
        cache_btn = QPushButton(self._cache_label)
        cache_btn.clicked.connect(self.drop_caches)
        cache_btn.setEnabled(self._cache_supported)
        self._cache_btn = cache_btn
        card.body.addWidget(cache_btn)
        self.body.addWidget(card)
        self.body.addStretch(1)

        monitor.stats_updated.connect(self.update_stats)
        self.refresh()

    def update_stats(self, stats: dict) -> None:
        ram = stats.get("ram", {})
        self._ram.set_value(
            f"{ram.get('percent', 0):.0f} %",
            f"{ram.get('used_gb', 0):.1f} / {ram.get('total_gb', 0):.1f} GB",
            percent=ram.get("percent", 0),
        )
        self._swap.set_value(
            f"{ram.get('swap_percent', 0):.0f} %",
            f"{ram.get('swap_used_gb', 0):.1f} / {ram.get('swap_total_gb', 0):.1f} GB",
            percent=ram.get("swap_percent", 0),
        )

    def refresh(self) -> None:
        state = self.memory.state()
        swappiness = state.get("swappiness")
        self._swappiness.set_value(
            str(swappiness) if swappiness is not None else "—",
            "valor actual del kernel" if swappiness is not None
            else "no disponible en Windows")
        max_map = state.get("max_map_count")
        self._rows["max_map"].set_value(
            str(max_map) if max_map is not None else "—")
        self._rows["drop"].set_value(
            "requiere tu contraseña" if self._cache_supported
            else "no disponible en este sistema")
        self._cache_btn.setText(self._cache_label)
        self._cache_btn.setEnabled(self._cache_supported)

    def drop_caches(self) -> None:
        if not self._cache_supported:
            return
        if not confirm(
            self,
            "Liberar cachés",
            "Se ejecutará «sync» y se vaciarán las cachés del kernel.\n\n"
            "No borra archivos, pero el sistema irá algo más lento unos "
            "segundos mientras vuelve a leer datos del disco.",
        ):
            return
        run_worker(
            self._cache_btn,
            lambda: apply_commands(self.memory.drop_caches_commands()),
            self._on_dropped,
            self._on_error,
            busy_text="Liberando…",
            parent=self,
        )

    def _on_dropped(self, result) -> None:
        ok, failed = result
        self._cache_btn.setText(self._cache_label)
        if failed:
            error_dialog(self, "No se pudo liberar la caché", "\n".join(failed))
        else:
            info_dialog(self, "Cachés liberadas",
                        "La caché del kernel se vació correctamente.")

    def _on_error(self, message: str) -> None:
        self._cache_btn.setText(self._cache_label)
        error_dialog(self, "Error de Cortex", message)


# ----------------------------------------------------------------------------
# Game Booster
# ----------------------------------------------------------------------------

class BoosterPage(Page):
    def __init__(self, booster, activity, config, parent: QWidget | None = None):
        super().__init__("Game Booster",
                         "Detecta el juego activo y prioriza su proceso",
                         parent)
        self.booster = booster
        self.activity = activity
        self.config = config

        card = Card()
        card.body.addWidget(SectionTitle("Juego detectado"))
        self._game = QLabel("Buscando…")
        self._game.setObjectName("metricValue")
        self._game.setWordWrap(True)
        card.body.addWidget(self._game)
        self._process = _muted("")
        card.body.addWidget(self._process)

        buttons = QHBoxLayout()
        self._boost_btn = QPushButton("Priorizar juego")
        self._boost_btn.setObjectName("accentButton")
        self._boost_btn.clicked.connect(self.boost)
        self._unboost_btn = QPushButton("Quitar prioridad")
        self._unboost_btn.clicked.connect(self.unboost)
        buttons.addWidget(self._boost_btn)
        buttons.addWidget(self._unboost_btn)
        buttons.addStretch(1)
        card.body.addLayout(buttons)
        self.body.addWidget(card)

        help_card = Card()
        help_card.body.addWidget(SectionTitle("Cómo funciona"))
        if platform_info.IS_WINDOWS:
            help_text = (
                "Cortex busca juegos en las carpetas habituales de Steam, "
                "Epic, GOG, Riot, Ubisoft y EA, o entre las ventanas "
                "visibles. Al priorizar se asigna prioridad Alta de Windows "
                "y se restaura la original con «Quitar prioridad». No se "
                "cierra ningún proceso y no hace falta elevar permisos.")
        else:
            help_text = (
                "Cortex detecta el juego por el registro de MangoHud. Al "
                "priorizarlo se le asigna más CPU (nice negativo) y prioridad "
                "de E/S, con un único pkexec. «Quitar prioridad» restaura el "
                "valor original. No se cierra ningún proceso.")
        help_card.body.addWidget(_muted(help_text))
        self.body.addWidget(help_card)
        self.body.addStretch(1)

        self._timer = QTimer(self)
        self._timer.setInterval(3000)
        self._timer.timeout.connect(self.refresh)
        self._timer.start()
        activity.changed.connect(self.refresh)
        self.refresh()

    def refresh(self) -> None:
        self._boost_btn.setText("Priorizar juego")
        self._unboost_btn.setText("Quitar prioridad")
        if not self.config.get("auto_detect_game", True):
            boosted = self.booster.boosted()
            self._game.setText("Detección automática desactivada")
            if boosted:
                self._process.setText(
                    f"Priorizado: {boosted.get('name', 'juego')} "
                    f"(PID {boosted.get('pid')})")
                self._unboost_btn.setEnabled(True)
            else:
                self._process.setText(
                    "Actívala en Ajustes para detectar juegos automáticamente.")
                self._unboost_btn.setEnabled(False)
            self._boost_btn.setEnabled(False)
            return
        game = self.booster.active_game()
        process = self.booster.find_process()
        boosted = self.booster.boosted()
        if game:
            self._game.setText(game["name"])
        else:
            self._game.setText("Ningún juego activo")
        if boosted:
            self._process.setText(
                f"Priorizado: {boosted.get('name', 'juego')} "
                f"(PID {boosted.get('pid')}, {boosted.get('boosted_at', '')})")
            self._unboost_btn.setEnabled(True)
            self._boost_btn.setEnabled(False)
        elif process:
            priority = ("prioridad de Windows" if platform_info.IS_WINDOWS
                        else f"nice {process['nice']}")
            self._process.setText(
                f"Proceso: {process['name']} · PID {process['pid']} · "
                f"{priority}")
            self._unboost_btn.setEnabled(False)
            self._boost_btn.setEnabled(True)
        else:
            self._process.setText(
                "Abre el juego (Steam, Epic, GOG o una ventana de juego) y "
                "espera unos segundos."
                if platform_info.IS_WINDOWS else
                "Abre un juego con MangoHud activo para detectarlo.")
            self._unboost_btn.setEnabled(False)
            self._boost_btn.setEnabled(bool(game))

    def boost(self) -> None:
        process = self.booster.find_process()
        if process is None:
            error_dialog(self, "Game Booster",
                         "No se pudo identificar el proceso del juego.")
            return
        if not confirm(
            self,
            "Priorizar juego",
            f"¿Dar más prioridad a «{process['name']}» (PID {process['pid']})?",
            detail=("Se asignará prioridad Alta de Windows. Es reversible y "
                    "no cierra ningún proceso."
                    if platform_info.IS_WINDOWS else
                    "Se usará nice -5 y prioridad de E/S. Es reversible y no "
                    "cierra ningún proceso."),
        ):
            return
        run_worker(
            self._boost_btn,
            self.booster.boost,
            self._on_result,
            self._on_error,
            busy_text="Priorizando…",
            parent=self,
        )

    def unboost(self) -> None:
        if not confirm(self, "Quitar prioridad",
                       "Se restaurará el nice original del juego."):
            return
        run_worker(
            self._unboost_btn,
            self.booster.unboost,
            self._on_result,
            self._on_error,
            busy_text="Restaurando…",
            parent=self,
        )

    def _on_result(self, result) -> None:
        ok, message = result
        self.refresh()
        if ok:
            info_dialog(self, "Game Booster", message)
        else:
            error_dialog(self, "Game Booster", message)

    def _on_error(self, message: str) -> None:
        self.refresh()
        error_dialog(self, "Error de Cortex", message)


# ----------------------------------------------------------------------------
# Actividad
# ----------------------------------------------------------------------------

class ActivityPage(Page):
    def __init__(self, activity, parent: QWidget | None = None):
        super().__init__("Actividad", "Registro propio de Cortex Gaming Engine",
                         parent)
        self.activity = activity

        card = Card()
        card.body.addWidget(SectionTitle("Últimos eventos"))
        self._list = ActivityList(activity)
        self._list.setMinimumHeight(320)
        card.body.addWidget(self._list, 1)

        buttons = QHBoxLayout()
        clear = QPushButton("Borrar registro")
        clear.setObjectName("restoreButton")
        clear.clicked.connect(self.clear)
        folder = QPushButton("Abrir carpeta del registro")
        folder.clicked.connect(self.open_folder)
        buttons.addWidget(clear)
        buttons.addWidget(folder)
        buttons.addStretch(1)
        card.body.addLayout(buttons)
        self.body.addWidget(card)

        self.body.addWidget(_muted(str(activity.path)))
        self.body.addStretch(1)

    def clear(self) -> None:
        if not confirm(self, "Borrar registro",
                       "¿Vaciar el registro de actividad de Cortex?",
                       danger=True):
            return
        self.activity.clear()
        self.activity.log("Registro de actividad vaciado.", "INFO")

    def open_folder(self) -> None:
        folder = self.activity.path.parent
        folder.mkdir(parents=True, exist_ok=True)
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder))):
            info_dialog(self, "Registro", str(self.activity.path))


# ----------------------------------------------------------------------------
# Ajustes (configuración propia + guardar/restaurar)
# ----------------------------------------------------------------------------

class SettingsPage(Page):
    def __init__(self, config, profiles, monitor, activity,
                 parent: QWidget | None = None):
        super().__init__("Ajustes",
                         "Configuración propia y guardado/restauración de Cortex",
                         parent)
        self.config = config
        self.profiles = profiles
        self.monitor = monitor
        self.activity = activity

        general = Card()
        general.body.addWidget(SectionTitle("Monitorización"))
        interval_row = QHBoxLayout()
        interval_row.addWidget(QLabel("Intervalo de muestreo (ms)"))
        self._interval = QSpinBox()
        self._interval.setRange(500, 10000)
        self._interval.setSingleStep(250)
        self._interval.setValue(int(config.get("monitor_interval_ms", 1500)))
        interval_row.addWidget(self._interval)
        interval_row.addStretch(1)
        general.body.addLayout(interval_row)

        self._auto = QCheckBox(
            "Detectar juegos automáticamente en Game Booster")
        self._auto.setChecked(bool(config.get("auto_detect_game", True)))
        general.body.addWidget(self._auto)

        save = QPushButton("Guardar configuración")
        save.setObjectName("accentButton")
        save.clicked.connect(self.save)
        general.body.addWidget(save)
        self.body.addWidget(general)

        files = Card()
        files.body.addWidget(SectionTitle("Guardar y restaurar configuración"))
        files.body.addWidget(_muted(
            "Puedes exportar tus ajustes de Cortex a un archivo y volver a "
            "importarlos en este u otro equipo. No incluye la posición de la "
            "ventana."))
        buttons = QHBoxLayout()
        export = QPushButton("Exportar…")
        export.clicked.connect(self.export)
        importer = QPushButton("Importar…")
        importer.clicked.connect(self.import_config)
        reset = QPushButton("Restablecer ajustes")
        reset.setObjectName("restoreButton")
        reset.clicked.connect(self.reset)
        buttons.addWidget(export)
        buttons.addWidget(importer)
        buttons.addWidget(reset)
        buttons.addStretch(1)
        files.body.addLayout(buttons)
        self.body.addWidget(files)

        restore = Card()
        restore.body.addWidget(SectionTitle("Estado del sistema"))
        self._snapshot = _muted(profiles.snapshot_info())
        restore.body.addWidget(self._snapshot)
        restore_btn = QPushButton("Restaurar valores originales del equipo")
        restore_btn.setObjectName("restoreButton")
        restore_btn.clicked.connect(self.restore_system)
        restore.body.addWidget(restore_btn)
        discard = QPushButton("Descartar instantánea guardada")
        discard.clicked.connect(self.discard_snapshot)
        restore.body.addWidget(discard)
        self._restore_btn = restore_btn
        self._discard_btn = discard
        self.body.addWidget(restore)

        paths = Card()
        paths.body.addWidget(SectionTitle("Ubicaciones"))
        paths.body.addWidget(_muted(
            f"Configuración: {config_path()}\n"
            f"Estado, registro e instantánea: {state_dir()}"))
        paths.body.addWidget(_muted(f"{APP_NAME} {APP_VERSION}"))
        self.body.addWidget(paths)
        self.body.addStretch(1)
        self.profiles.changed.connect(self._update_snapshot_state)
        self._update_snapshot_state()

    # ------------------------------------------------------------------

    def _update_snapshot_state(self) -> None:
        available = self.profiles.has_snapshot()
        self._snapshot.setText(self.profiles.snapshot_info())
        self._restore_btn.setText("Restaurar valores originales del equipo")
        self._restore_btn.setEnabled(available)
        self._discard_btn.setEnabled(available)

    def save(self) -> None:
        self.config.set("monitor_interval_ms", int(self._interval.value()))
        self.config.set("auto_detect_game", self._auto.isChecked())
        self.config.save()
        self.monitor.set_interval(int(self._interval.value()))
        self.activity.log("Configuración de Cortex guardada.", "OK")
        info_dialog(self, "Ajustes", "Configuración guardada.")

    def export(self) -> None:
        default = str(Path.home() / "cortex-gaming-engine.json")
        path, _filter = QFileDialog.getSaveFileName(
            self, "Exportar configuración de Cortex", default,
            "Configuración JSON (*.json)")
        if not path:
            return
        try:
            self.config.export_to(path)
        except OSError as exc:
            error_dialog(self, "No se pudo exportar", str(exc))
            return
        self.activity.log(f"Configuración exportada a {path}", "OK")
        info_dialog(self, "Exportado", f"Configuración guardada en:\n{path}")

    def import_config(self) -> None:
        path, _filter = QFileDialog.getOpenFileName(
            self, "Importar configuración de Cortex", str(Path.home()),
            "Configuración JSON (*.json)")
        if not path:
            return
        try:
            keys = self.config.import_from(path)
        except (OSError, ValueError) as exc:
            error_dialog(self, "No se pudo importar", str(exc))
            return
        self._interval.setValue(int(self.config.get("monitor_interval_ms", 1500)))
        self._auto.setChecked(bool(self.config.get("auto_detect_game", True)))
        self.monitor.set_interval(int(self._interval.value()))
        self.activity.log(
            f"Configuración importada desde {path} ({', '.join(keys)}).", "OK")
        info_dialog(self, "Importado",
                    f"Se importaron {len(keys)} ajustes.")

    def reset(self) -> None:
        if not confirm(self, "Restablecer ajustes",
                       "¿Volver a la configuración predeterminada de Cortex?",
                       danger=True):
            return
        self.config.reset()
        self.config.save()
        self._interval.setValue(int(self.config.get("monitor_interval_ms", 1500)))
        self._auto.setChecked(bool(self.config.get("auto_detect_game", True)))
        self.monitor.set_interval(int(self._interval.value()))
        self.activity.log("Configuración de Cortex restablecida.", "INFO")
        info_dialog(self, "Ajustes", "Configuración restablecida.")

    def restore_system(self) -> None:
        if not confirm(self, "Restaurar sistema",
                       ("Se devolverá el plan de energía del sistema a su "
                        "valor original."
                        if platform_info.IS_WINDOWS else
                        "Se devolverán CPU, GPU y memoria a sus valores "
                        "originales."),
                       detail=self.profiles.snapshot_info()):
            return
        run_worker(
            self._restore_btn,
            self.profiles.revert,
            self._on_restored,
            self._on_error,
            busy_text="Restaurando…",
            parent=self,
        )

    def _on_restored(self, result) -> None:
        ok, failed = result
        self._update_snapshot_state()
        if failed:
            error_dialog(self, "Restauración incompleta", "\n".join(failed))
        elif ok:
            info_dialog(self, "Restauración completada",
                        f"Se restauraron {len(ok)} ajustes.")

    def discard_snapshot(self) -> None:
        if not confirm(
            self, "Descartar instantánea",
            "Se borrarán los valores originales guardados. Si todavía hay "
            "cambios aplicados, ya no podrás revertirlos desde Cortex.",
            danger=True,
        ):
            return
        self.profiles.store.clear()
        self._update_snapshot_state()
        self.activity.log("Instantánea de valores originales descartada.", "WARN")

    def _on_error(self, message: str) -> None:
        self._update_snapshot_state()
        error_dialog(self, "Error de Cortex", message)
