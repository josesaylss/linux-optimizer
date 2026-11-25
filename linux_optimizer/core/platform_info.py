"""Detección de plataforma para mantener un único código Linux/Windows.

Los módulos deben consultar ``platform_info.IS_WINDOWS`` en tiempo de
ejecución (no copiarlo a una constante local) para que las pruebas puedan
simular otras plataformas.
"""

from __future__ import annotations

import os
import sys

IS_WINDOWS = os.name == "nt"
IS_LINUX = sys.platform.startswith("linux")
IS_MACOS = sys.platform == "darwin"


def platform_name() -> str:
    if IS_WINDOWS:
        return "Windows"
    if IS_LINUX:
        return "Linux"
    if IS_MACOS:
        return "macOS"
    return sys.platform or os.name
