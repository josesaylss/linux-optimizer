"""Sesiones de la aplicación única: Linux Optimizer y Cortex Gaming Engine.

Ambas sesiones usan el **mismo ejecutable**:

    linux-optimizer             → sesión Linux Optimizer
    linux-optimizer --cortex    → sesión Cortex Gaming Engine

Cada sesión se abre en su propia ventana y proceso, de modo que abrir o
cerrar Cortex nunca cierra Linux Optimizer (y al revés). En el código fuente
se usa ``python -m linux_optimizer``; en el .exe de Windows, el propio
ejecutable.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

from linux_optimizer.core import platform_info


def app_root() -> Path | None:
    """Raíz donde viven los paquetes (repo, portable o RPM instalado)."""
    root = Path(__file__).resolve().parents[2]
    if (root / "linux_optimizer").is_dir() and (root / "cortex_engine").is_dir():
        return root
    return None


def cortex_available() -> bool:
    if app_root() is not None:
        return True
    try:
        return importlib.util.find_spec("cortex_engine") is not None
    except (ImportError, ValueError):
        return False


def _session_command(*extra: str) -> list[str]:
    if getattr(sys, "frozen", False):
        return [sys.executable, *extra]
    return [sys.executable, "-m", "linux_optimizer", *extra]


def cortex_command() -> list[str] | None:
    """Comando para la sesión Cortex, o ``None`` si no está instalada."""
    if not cortex_available():
        return None
    return _session_command("--cortex")


def optimizer_command() -> list[str]:
    """Comando para la sesión Linux Optimizer."""
    return _session_command()


def _launch(command: list[str]) -> tuple[bool, str]:
    root = None if getattr(sys, "frozen", False) else app_root()
    kwargs: dict = {
        "cwd": str(root) if root is not None else None,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
    }
    if platform_info.IS_WINDOWS:
        kwargs["creationflags"] = (
            subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS)
    else:
        kwargs["start_new_session"] = True
    try:
        subprocess.Popen(command, **kwargs)
    except OSError as exc:
        return False, f"No se pudo abrir la sesión: {exc}"
    return True, "Sesión abierta."


def launch_cortex() -> tuple[bool, str]:
    """Abre la sesión Cortex de la misma aplicación."""
    command = cortex_command()
    if command is None:
        return False, (
            "No se encontró Cortex Gaming Engine. Reinstala Linux Optimizer "
            "o ejecuta la aplicación desde su carpeta completa.")
    ok, _message = _launch(command)
    if ok:
        return True, "Cortex Gaming Engine se está abriendo en otra sesión…"
    return ok, _message


def launch_optimizer() -> tuple[bool, str]:
    """Abre la sesión Linux Optimizer de la misma aplicación."""
    ok, _message = _launch(optimizer_command())
    if ok:
        return True, "Linux Optimizer se está abriendo en otra sesión…"
    return ok, _message
