"""Recursos embebidos del paquete (ícono de aplicación)."""

from __future__ import annotations

import pathlib

from linux_optimizer.core import platform_info

SVG_ICON_PATH = pathlib.Path(__file__).with_name("linux-optimizer.svg")
ICO_ICON_PATH = pathlib.Path(__file__).with_name("linux-optimizer.ico")

# Windows usa .ico para la ventana y para el .exe; Linux usa el SVG.
ICON_PATH = (
    ICO_ICON_PATH
    if platform_info.IS_WINDOWS and ICO_ICON_PATH.exists()
    else SVG_ICON_PATH
)
