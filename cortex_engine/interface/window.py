"""Vista de Cortex Gaming Engine dentro de la ventana de la aplicación.

Cortex es un **modo de la misma ventana**: conserva su barra lateral, tema,
configuración, monitor y registro, pero se alterna con Linux Optimizer sin
abrir otra ventana ni otro proceso. ``--cortex`` inicia la app directamente
en este modo.
"""

from __future__ import annotations

from PySide6.QtCore import QByteArray, QSize, Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from cortex_engine import APP_NAME, APP_VERSION
from cortex_engine.config import CortexConfig
from cortex_engine.cpu.module import CpuModule
from cortex_engine.cpu.windows_module import WindowsCpuModule
from cortex_engine.gaming.booster import GameBooster
from cortex_engine.gpu.module import GpuModule
from cortex_engine.interface.pages import (
    ActivityPage,
    BoosterPage,
    CpuPage,
    GpuPage,
    MemoryPage,
    PanelPage,
    ProfilesPage,
    SettingsPage,
)
from cortex_engine.memory.module import MemoryModule
from cortex_engine.memory.windows import WindowsMemoryModule
from cortex_engine.monitoring.activity import ActivityLog
from cortex_engine.monitoring.engine import CortexMonitor
from cortex_engine.profiles.manager import ProfileManager, PROFILE_MAP
from cortex_engine.profiles.windows import WindowsProfileManager
from cortex_engine.restore.store import RestoreStore
from linux_optimizer.core import platform_info
from linux_optimizer.resources import ICON_PATH
from linux_optimizer.ui.widgets import error_dialog, wait_for_workers


class CortexWindow(QWidget):
    """Vista con los ocho módulos de Cortex Gaming Engine.

    Es un QWidget para poder vivir dentro de la ventana principal. Si se
    muestra como ventana independiente, Qt la trata como tal sin cambios.
    """

    def __init__(self, config: CortexConfig | None = None,
                 parent: QWidget | None = None,
                 on_optimizer=None,
                 standalone: bool | None = None):
        super().__init__(parent)
        self._on_optimizer = on_optimizer
        self._standalone = (parent is None if standalone is None
                            else standalone)
        self.setObjectName("cortexModeRoot")
        self.setWindowTitle(f"{APP_NAME} {APP_VERSION}")
        self.resize(1120, 720)
        self.setMinimumSize(QSize(940, 600))
        self.setWindowIcon(QIcon(str(ICON_PATH)))

        # ---------------- Motor del modo Cortex ----------------
        self.config = config if config is not None else CortexConfig()
        self.activity = ActivityLog()
        self.store = RestoreStore()
        if platform_info.IS_WINDOWS:
            self.cpu = WindowsCpuModule()
            self.gpu = GpuModule()
            self.memory = WindowsMemoryModule()
            self.profiles = WindowsProfileManager(
                self.config, self.activity, self.store)
        else:
            self.cpu = CpuModule()
            self.gpu = GpuModule()
            self.memory = MemoryModule()
            self.profiles = ProfileManager(
                self.config, self.activity, self.cpu, self.gpu, self.memory,
                self.store)
        self.booster = GameBooster(activity=self.activity)
        self.monitor = CortexMonitor(
            int(self.config.get("monitor_interval_ms", 1500)), self)

        root = QWidget()
        root.setObjectName("cortexRoot")
        layout = QHBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        layout.addWidget(self._build_sidebar())
        layout.addWidget(self._build_right(), 1)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(root)

        self._build_pages()
        self.profiles.changed.connect(self._refresh_all)
        self._restore_geometry()
        self._refresh_all()
        self.set_active(True)
        self.activity.log(f"{APP_NAME} iniciado.", "INFO")

    # ------------------------------------------------------------------
    # Construcción
    # ------------------------------------------------------------------

    def _build_sidebar(self) -> QListWidget:
        self.sidebar = QListWidget()
        self.sidebar.setObjectName("cortexSidebar")
        self.sidebar.setFixedWidth(216)
        self.sidebar.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.sidebar.setIconSize(QSize(18, 18))

        self._entries = (
            ("◈", "Panel", self._page_panel),
            ("◆", "Perfiles", self._page_profiles),
            ("▣", "CPU", self._page_cpu),
            ("◉", "GPU", self._page_gpu),
            ("▤", "RAM", self._page_memory),
            ("▶", "Game Booster", self._page_booster),
            ("☰", "Actividad", self._page_activity),
            ("⚙", "Ajustes", self._page_settings),
        )
        for icon, name, _builder in self._entries:
            item = QListWidgetItem(f"{icon}   {name}")
            item.setSizeHint(QSize(190, 42))
            self.sidebar.addItem(item)

        self.sidebar.currentRowChanged.connect(self._switch_page)
        return self.sidebar

    def _build_right(self) -> QWidget:
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(0)

        header = QFrame()
        header.setObjectName("cortexHeader")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(24, 14, 24, 14)
        header_layout.setSpacing(12)

        titles = QVBoxLayout()
        titles.setSpacing(0)
        logo = QLabel("CORTEX")
        logo.setObjectName("cortexLogo")
        tagline = QLabel("GAMING ENGINE")
        tagline.setObjectName("cortexTagline")
        titles.addWidget(logo)
        titles.addWidget(tagline)
        header_layout.addLayout(titles)
        header_layout.addStretch(1)

        # Misma ventana: volver al modo Linux Optimizer.
        self._optimizer_btn = QPushButton("Linux Optimizer")
        self._optimizer_btn.setObjectName("sessionSwitch")
        self._optimizer_btn.setToolTip("Volver al modo Linux Optimizer")
        self._optimizer_btn.clicked.connect(self._open_optimizer)
        header_layout.addWidget(self._optimizer_btn)

        self._status_pill = QLabel("SIN PERFIL")
        self._status_pill.setObjectName("statusPill")
        header_layout.addWidget(self._status_pill)
        right_layout.addWidget(header)

        self.stack = QStackedWidget()
        right_layout.addWidget(self.stack, 1)
        return right

    # ------------------------------------------------------------------
    # Páginas
    # ------------------------------------------------------------------

    def _page_panel(self) -> PanelPage:
        return PanelPage(self.monitor, self.cpu, self.gpu, self.memory,
                         self.profiles, self.activity)

    def _page_profiles(self) -> ProfilesPage:
        return ProfilesPage(self.profiles)

    def _page_cpu(self) -> CpuPage:
        return CpuPage(self.cpu, self.profiles)

    def _page_gpu(self) -> GpuPage:
        return GpuPage(self.gpu)

    def _page_memory(self) -> MemoryPage:
        return MemoryPage(self.memory, self.monitor)

    def _page_booster(self) -> BoosterPage:
        return BoosterPage(self.booster, self.activity, self.config)

    def _page_activity(self) -> ActivityPage:
        return ActivityPage(self.activity)

    def _page_settings(self) -> SettingsPage:
        return SettingsPage(self.config, self.profiles, self.monitor,
                            self.activity)

    def _build_pages(self) -> None:
        builders = (
            self._page_panel, self._page_profiles, self._page_cpu,
            self._page_gpu, self._page_memory, self._page_booster,
            self._page_activity, self._page_settings,
        )
        self.pages = []
        for builder in builders:
            page = builder()
            self.pages.append(page)
            self.stack.addWidget(page)

    def _switch_page(self, row: int) -> None:
        if 0 <= row < self.stack.count():
            self.stack.setCurrentIndex(row)

    def _open_optimizer(self) -> None:
        """Vuelve al modo Linux Optimizer de la misma ventana."""
        if self._on_optimizer is not None:
            self._on_optimizer()
            return
        # Uso independiente (sin ventana principal): se inicia la aplicación.
        from linux_optimizer.core.cortex_launcher import launch_optimizer
        ok, message = launch_optimizer()
        if ok:
            self.activity.log(message, "INFO")
        else:
            error_dialog(self, "Linux Optimizer", message)

    def set_active(self, active: bool) -> None:
        """Activa/desactiva la monitorización según el modo visible."""
        if active:
            self.monitor.start()
        else:
            self.monitor.stop()

    # ------------------------------------------------------------------

    def _refresh_all(self) -> None:
        active = self.profiles.active()
        if active:
            profile = PROFILE_MAP[active]
            self._status_pill.setText(f"PERFIL: {profile.title}")
            self._status_pill.setStyleSheet(f"color: {profile.accent};")
        else:
            self._status_pill.setText("SIN PERFIL")
            self._status_pill.setStyleSheet("")
        for page in getattr(self, "pages", []):
            refresh = getattr(page, "refresh", None)
            if callable(refresh):
                refresh()

    # ------------------------------------------------------------------
    # Geometría y cierre
    # ------------------------------------------------------------------

    def _restore_geometry(self) -> None:
        if not self._standalone:
            return  # integrada en la ventana principal: comparte su geometría
        stored = self.config.get("window_geometry", "")
        if not stored:
            return
        try:
            self.restoreGeometry(QByteArray.fromBase64(stored.encode("ascii")))
        except (ValueError, TypeError):
            pass

    def save_geometry(self) -> None:
        data = bytes(self.saveGeometry().toBase64()).decode("ascii")
        self.config.set("window_geometry", data)
        self.config.save()

    def closeEvent(self, event) -> None:  # noqa: N802 (Qt)
        self.monitor.stop()
        self.save_geometry()
        self.activity.log(f"{APP_NAME} cerrado.", "INFO")
        wait_for_workers()
        super().closeEvent(event)


def build_window(config: CortexConfig | None = None) -> CortexWindow:
    """Crea la ventana con todas sus páginas (útil para pruebas)."""
    window = CortexWindow(config)
    window.sidebar.setCurrentRow(0)
    return window
