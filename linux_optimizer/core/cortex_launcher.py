"""Acceso de Linux Optimizer a Cortex Gaming Engine.

Cortex se abre como **proceso independiente**: tiene su propia ventana, tema,
configuración y monitor. Linux Optimizer solo lanza el proceso y no comparte
estado con él, así que abrir o cerrar Cortex nunca cierra la aplicación
principal.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path


def cortex_root() -> Path | None:
    """Raíz donde vive el paquete ``cortex_engine`` (repo, portable o RPM)."""
    root = Path(__file__).resolve().parents[2]
    return root if (root / "cortex_engine").is_dir() else None


def cortex_available() -> bool:
    if cortex_root() is not None:
        return True
    try:
        return importlib.util.find_spec("cortex_engine") is not None
    except (ImportError, ValueError):
        return False


def cortex_command() -> list[str] | None:
    """Comando para abrir Cortex, o ``None`` si no está instalado."""
    if not cortex_available():
        return None
    return [sys.executable, "-m", "cortex_engine"]


def launch_cortex() -> tuple[bool, str]:
    """Abre Cortex en segundo plano. Devuelve ``(abierto, mensaje)``."""
    command = cortex_command()
    if command is None:
        return False, (
            "No se encontró Cortex Gaming Engine. Reinstala Linux Optimizer "
            "o ejecuta la aplicación desde su carpeta completa.")
    root = cortex_root()
    try:
        subprocess.Popen(
            command,
            cwd=str(root) if root is not None else None,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError as exc:
        return False, f"No se pudo abrir Cortex Gaming Engine: {exc}"
    return True, "Cortex Gaming Engine se está abriendo…"
