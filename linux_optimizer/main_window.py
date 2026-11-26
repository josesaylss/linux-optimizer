"""Ventana principal con navegación lateral."""

from __future__ import annotations

import platform

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QPushButton,
    QStackedWidget,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)

from linux_optimizer import APP_NAME, __version__
from linux_optimizer.core import platform_info
from linux_optimizer.core.backup import BackupStore
from linux_optimizer.core.distro import DistroInfo, detect_distro
from linux_optimizer.core.gaming import GamingManager
from linux_optimizer.core.monitor import SystemMonitor
from linux_optimizer.resources import ICON_PATH
from linux_optimizer.theme import THEME_QSS
from linux_optimizer.ui.about_page import AboutPage
from linux_optimizer.ui.cleaner_page import CleanerPage
from linux_optimizer.ui.dashboard import DashboardPage
from linux_optimizer.ui.diagnostics_page import DiagnosticsPage
from linux_optimizer.ui.gaming_page import GamingPage
from linux_optimizer.ui.hud_controller import HudController
from linux_optimizer.ui.power_page import PowerPage
from linux_optimizer.ui.services_page import ServicesPage
from linux_optimizer.ui.widgets import Card  # noqa: F401 (estilo común)
from linux_optimizer.ui.widgets import wait_for_workers

_PAGES = (
    ("🖥", "Panel de rendimiento", DashboardPage),
    ("🧹", "Limpieza segura", CleanerPage),
    ("🎮", "Modo Gaming", GamingPage),
    ("⚙️", "Servicios del sistema", ServicesPage),
    ("🔋", "Energía", PowerPage),
    ("🩺", "Diagnóstico", DiagnosticsPage),
    ("ℹ️", "Acerca de", AboutPage),
)

# En Windows se ocultan las páginas que dependen de systemd/sysfs/pkexec.
# Cortex Gaming Engine sigue disponible desde el botón de la cabecera.
_PAGES_WINDOWS = tuple(
    entry for entry in _PAGES
    if entry[2] not in (GamingPage, ServicesPage, PowerPage)
)


def pages_for_platform() -> tuple:
    return _PAGES_WINDOWS if platform_info.IS_WINDOWS else _PAGES


class MainWindow(QMainWindow):
    def __init__(self, mode: str = "optimizer"):
        super().__init__()
        self._mode = "optimizer"
        self._cortex_view = None
        self.setWindowTitle(f"{APP_NAME} {__version__}")
        self.resize(1180, 760)
        self.setMinimumSize(QSize(960, 620))

        self.distro: DistroInfo = detect_distro()
        self.backup_store = BackupStore()
        self.monitor = SystemMonitor()
        if platform_info.IS_WINDOWS:
            self.gaming_manager = None
            self.hud = None
        else:
            self.gaming_manager = GamingManager(self.backup_store)
            self.hud = HudController(self)
        self._pages_spec = pages_for_platform()

        central = QWidget()
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ---------------- Barra lateral ----------------
        self.sidebar = QListWidget()
        self.sidebar.setObjectName("sidebar")
        self.sidebar.setIconSize(QSize(20, 20))
        self.sidebar.setFixedWidth(230)
        self.sidebar.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        for icon, name, _page in self._pages_spec:
            item = QListWidgetItem(f"{icon}   {name}")
            item.setSizeHint(QSize(200, 44))
            self.sidebar.addItem(item)

        # Pie de la barra lateral con info de distro.
        self.sidebar.addItem(QListWidgetItem(""))

        root.addWidget(self.sidebar)

        # ---------------- Columna derecha ----------------
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(24, 18, 24, 12)
        right_layout.setSpacing(14)

        header = QHBoxLayout()
        header_text = QVBoxLayout()
        self._title = QLabel(APP_NAME)
        self._title.setObjectName("headerTitle")
        self._subtitle = QLabel(self.distro.pretty + f"  ·  kernel {platform.release()}")
        self._subtitle.setObjectName("headerSubtitle")
        header_text.addWidget(self._title)
        header_text.addWidget(self._subtitle)
        header.addLayout(header_text)
        header.addStretch(1)

        # Cambio de modo dentro de la misma ventana (sin segundo proceso).
        self._cortex_btn = QPushButton("◈ Cortex Gaming Engine")
        self._cortex_btn.setObjectName("cortexLaunch")
        self._cortex_btn.setToolTip("Cambiar al modo Cortex en esta ventana")
        self._cortex_btn.clicked.connect(self._open_cortex)
        header.addWidget(self._cortex_btn, 0, Qt.AlignmentFlag.AlignVCenter)

        right_layout.addLayout(header)

        self.stack = QStackedWidget()
        right_layout.addWidget(self.stack, 1)

        root.addWidget(right, 1)

        # Un única ventana con dos modos: Optimizer (índice 0) y Cortex (1).
        self._mode_stack = QStackedWidget(self)
        self._mode_stack.addWidget(central)
        self.setCentralWidget(self._mode_stack)

        # ---------------- Páginas ----------------
        self._pages = []
        for icon, name, page_class in self._pages_spec:
            page = self._build_page(page_class)
            self._pages.append(page)
            self.stack.addWidget(page)

        self.sidebar.currentRowChanged.connect(self._switch_page)
        self.sidebar.setCurrentRow(0)

        self.statusBar().showMessage(
            "Modo seguro: toda acción de sistema pide confirmación y crea respaldo.")

        self._setup_tray()
        self.monitor.start()
        if mode == "cortex":
            self.set_mode("cortex")

    # ------------------------------------------------------------------

    def _setup_tray(self) -> None:
        """Icono en la bandeja del sistema (si el escritorio lo soporta)."""
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        self._tray = QSystemTrayIcon(QIcon(str(ICON_PATH)), self)
        self._tray.setToolTip(f"{APP_NAME} {__version__}")
        menu = QMenu()
        action_toggle = QAction("Mostrar / ocultar", menu)
        action_toggle.triggered.connect(self._toggle_visible)
        menu.addAction(action_toggle)
        if self.hud is not None:
            self._action_hud = QAction("HUD de rendimiento", menu)
            self._action_hud.setCheckable(True)
            self._action_hud.setChecked(False)
            self._action_hud.toggled.connect(
                lambda on: self.hud.show() if on else self.hud.hide())
            self.hud.hidden.connect(self._sync_hud_action)
            self.hud.started.connect(self._mark_hud_action)
            menu.addAction(self._action_hud)
        menu.addSeparator()
        action_cortex = QAction("◈ Modo Cortex Gaming Engine", menu)
        action_cortex.triggered.connect(self._open_cortex)
        menu.addAction(action_cortex)
        menu.addSeparator()
        action_quit = QAction("Salir", menu)
        action_quit.triggered.connect(self.close)
        menu.addAction(action_quit)
        self._tray.setContextMenu(menu)
        self._tray.activated.connect(
            lambda _reason: self._toggle_visible())
        self._tray.show()

    def _toggle_visible(self) -> None:
        self.setVisible(not self.isVisible())
        if self.isVisible():
            self.raise_()
            self.activateWindow()

    def _sync_hud_action(self) -> None:
        action = getattr(self, "_action_hud", None)
        if action is not None and action.isChecked():
            action.blockSignals(True)
            action.setChecked(False)
            action.blockSignals(False)

    def _mark_hud_action(self) -> None:
        action = getattr(self, "_action_hud", None)
        if action is not None and not action.isChecked():
            action.blockSignals(True)
            action.setChecked(True)
            action.blockSignals(False)

    def _open_cortex(self) -> None:
        """Cambia esta ventana al modo Cortex Gaming Engine."""
        self.set_mode("cortex")

    def _ensure_cortex_view(self):
        if self._cortex_view is None:
            from cortex_engine.interface.window import CortexWindow
            self._cortex_view = CortexWindow(
                on_optimizer=self._back_to_optimizer, standalone=False)
            self._mode_stack.addWidget(self._cortex_view)
        return self._cortex_view

    def _back_to_optimizer(self) -> None:
        self.set_mode("optimizer")

    def set_mode(self, mode: str) -> None:
        """Alterna los modos de la ventana sin crear otro proceso."""
        app = QApplication.instance()
        if mode == "cortex":
            view = self._ensure_cortex_view()
            view.set_active(True)
            self._mode_stack.setCurrentWidget(view)
            self.setWindowTitle(f"Cortex Gaming Engine · {APP_NAME}")
            if app is not None:
                from cortex_engine.interface.theme import CORTEX_QSS
                app.setStyleSheet(CORTEX_QSS)
            self.statusBar().showMessage("Modo Cortex Gaming Engine activo.", 4000)
        else:
            if self._cortex_view is not None:
                self._cortex_view.save_geometry()
                self._cortex_view.set_active(False)
            self._mode_stack.setCurrentIndex(0)
            self.setWindowTitle(f"{APP_NAME} {__version__}")
            if app is not None:
                app.setStyleSheet(THEME_QSS)
            self.statusBar().showMessage("Modo Linux Optimizer activo.", 4000)
        self._mode = mode

    def _build_page(self, page_class):
        if page_class is DashboardPage:
            return DashboardPage(self.monitor, self.distro)
        if page_class is CleanerPage:
            return CleanerPage(self.distro)
        if page_class is GamingPage:
            return GamingPage(self.gaming_manager, self.hud)
        if page_class is ServicesPage:
            return ServicesPage(self.backup_store)
        if page_class is PowerPage:
            return PowerPage(self.backup_store)
        if page_class is DiagnosticsPage:
            return DiagnosticsPage(self.distro)
        if page_class is AboutPage:
            return AboutPage(self.backup_store, self.distro)
        raise ValueError(page_class)

    def _switch_page(self, row: int) -> None:
        if 0 <= row < self.stack.count():
            self.stack.setCurrentIndex(row)

    def closeEvent(self, event):  # noqa: N802 (Qt)
        if self.hud is not None:
            self.hud.shutdown()
        self.monitor.stop()
        if self._cortex_view is not None:
            self._cortex_view.save_geometry()
            self._cortex_view.set_active(False)
        wait_for_workers()
        super().closeEvent(event)
