# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec para el .exe de Windows de la aplicación única.

Linux Optimizer y Cortex Gaming Engine comparten este ejecutable:

    LinuxOptimizer.exe             → modo Linux Optimizer
    LinuxOptimizer.exe --cortex    → modo Cortex Gaming Engine

Compilar en Windows (no se puede cross-compilar desde Linux):

    packaging\\windows\\build-exe.ps1

Resultado: dist\\LinuxOptimizer.exe
"""

from pathlib import Path

ROOT = Path(SPECPATH).resolve().parents[1]

ENTRY = ROOT / "packaging" / "windows" / "linux_optimizer_win.py"
ICON = ROOT / "linux_optimizer" / "resources" / "linux-optimizer.ico"
VERSION_FILE = ROOT / "packaging" / "windows" / "version_info.txt"

# Recursos que PyInstaller no descubre solo (QSS e iconos).
datas = [
    (str(ROOT / "cortex_engine" / "interface" / "theme.qss"),
     "cortex_engine/interface"),
    (str(ROOT / "linux_optimizer" / "resources" / "linux-optimizer.svg"),
     "linux_optimizer/resources"),
    (str(ICON), "linux_optimizer/resources"),
]

# El modo Cortex se importa dentro de una función; se declara explícitamente
# para que el análisis estático nunca la omita.
hiddenimports = [
    "cortex_engine",
    "cortex_engine.main",
    "cortex_engine.interface.window",
    "cortex_engine.interface.pages",
    "cortex_engine.interface.theme",
    "cortex_engine.cpu.windows",
    "cortex_engine.cpu.windows_module",
    "cortex_engine.memory.windows",
    "cortex_engine.profiles.windows",
]

# Módulos de Qt que la aplicación no usa; reducen el tamaño del .exe.
excludes = [
    "tkinter",
    "PySide6.Qt3DAnimation",
    "PySide6.Qt3DCore",
    "PySide6.Qt3DExtras",
    "PySide6.Qt3DInput",
    "PySide6.Qt3DLogic",
    "PySide6.Qt3DRender",
    "PySide6.QtBluetooth",
    "PySide6.QtCharts",
    "PySide6.QtDataVisualization",
    "PySide6.QtMultimedia",
    "PySide6.QtMultimediaWidgets",
    "PySide6.QtPdf",
    "PySide6.QtPdfWidgets",
    "PySide6.QtPositioning",
    "PySide6.QtQml",
    "PySide6.QtQuick",
    "PySide6.QtQuick3D",
    "PySide6.QtQuickWidgets",
    "PySide6.QtSerialPort",
    "PySide6.QtSql",
    "PySide6.QtTest",
    "PySide6.QtWebChannel",
    "PySide6.QtWebEngineCore",
    "PySide6.QtWebEngineQuick",
    "PySide6.QtWebEngineWidgets",
    "PySide6.QtWebSockets",
]

a = Analysis(
    [str(ENTRY)],
    pathex=[str(ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="LinuxOptimizer",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(ICON),
    version=str(VERSION_FILE),
)
