"""Prueba de humo de la GUI: la ventana se construye sin errores.

Se ejecuta con la plataforma offscreen para no necesitar servidor gráfico.
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication  # noqa: E402

from linux_optimizer.core.backup import BackupStore  # noqa: E402
from linux_optimizer.core.distro import detect_distro  # noqa: E402
from linux_optimizer.main_window import MainWindow  # noqa: E402
from linux_optimizer.theme import THEME_QSS  # noqa: E402


@pytest.fixture(scope="module")
def app():
    app = QApplication.instance() or QApplication([])
    yield app


def test_theme_not_empty():
    assert "QListWidget#sidebar" in THEME_QSS


def test_main_window_builds_and_updates(app, tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    window = MainWindow(app=app) if False else MainWindow()
    assert window.stack.count() == len(window._pages)
    for page in window._pages:
        assert page is not None

    # Un tick del monitor no debe fallar y debe emitir estadísticas.
    received = []
    window.monitor.stats_updated.connect(lambda s: received.append(s))
    stats = window.monitor.collect_once()
    assert "cpu" in stats and "mem" in stats and "disks" in stats
    assert received

    # Cambiar de página no debe fallar.
    window.sidebar.setCurrentRow(2)
    assert window.stack.currentIndex() == 2

    window.monitor.stop()
    window.close()


def test_backup_store_is_shared(app, tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    store = BackupStore()
    assert store.base_dir.is_dir()
