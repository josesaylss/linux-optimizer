"""Ventana principal con navegación lateral."""

from __future__ import annotations

import platform

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from linux_optimizer import APP_NAME, __version__
from linux_optimizer.core.backup import BackupStore
from linux_optimizer.core.distro import DistroInfo, detect_distro
from linux_optimizer.core.gaming import GamingManager
from linux_optimizer.core.monitor import SystemMonitor
from linux_optimizer.ui.cleaner_page import CleanerPage
from linux_optimizer.ui.dashboard import DashboardPage
from linux_optimizer.ui.diagnostics_page import DiagnosticsPage
from linux_optimizer.ui.gaming_page import GamingPage
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
)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} {__version__}")
        self.resize(1180, 760)
        self.setMinimumSize(QSize(960, 620))

        self.distro: DistroInfo = detect_distro()
        self.backup_store = BackupStore()
        self.monitor = SystemMonitor()
        self.gaming_manager = GamingManager(self.backup_store)

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

        for icon, name, _page in _PAGES:
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

        header = QVBoxLayout()
        self._title = QLabel(APP_NAME)
        self._title.setObjectName("headerTitle")
        self._subtitle = QLabel(self.distro.pretty + f"  ·  kernel {platform.release()}")
        self._subtitle.setObjectName("headerSubtitle")
        header.addWidget(self._title)
        header.addWidget(self._subtitle)
        right_layout.addLayout(header)

        self.stack = QStackedWidget()
        right_layout.addWidget(self.stack, 1)

        root.addWidget(right, 1)
        self.setCentralWidget(central)

        # ---------------- Páginas ----------------
        self._pages = []
        for icon, name, page_class in _PAGES:
            page = self._build_page(page_class)
            self._pages.append(page)
            self.stack.addWidget(page)

        self.sidebar.currentRowChanged.connect(self._switch_page)
        self.sidebar.setCurrentRow(0)

        self.statusBar().showMessage(
            "Modo seguro: toda acción de sistema pide confirmación y crea respaldo.")

        self.monitor.start()

    # ------------------------------------------------------------------

    def _build_page(self, page_class):
        if page_class is DashboardPage:
            return DashboardPage(self.monitor, self.distro)
        if page_class is CleanerPage:
            return CleanerPage(self.distro)
        if page_class is GamingPage:
            return GamingPage(self.gaming_manager)
        if page_class is ServicesPage:
            return ServicesPage(self.backup_store)
        if page_class is PowerPage:
            return PowerPage(self.backup_store)
        if page_class is DiagnosticsPage:
            return DiagnosticsPage(self.distro)
        raise ValueError(page_class)

    def _switch_page(self, row: int) -> None:
        if 0 <= row < self.stack.count():
            self.stack.setCurrentIndex(row)

    def closeEvent(self, event):  # noqa: N802 (Qt)
        self.monitor.stop()
        wait_for_workers()
        super().closeEvent(event)
