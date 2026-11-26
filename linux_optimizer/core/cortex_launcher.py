"""Utilidades de línea de comandos para la aplicación única.

La interfaz ya no abre procesos adicionales: los modos Optimizer y Cortex se
alternan dentro de la misma ventana (``MainWindow.set_mode``). Estas funciones
se conservan solo para lanzar el ejecutable desde scripts externos:

    linux-optimizer             → modo Linux Optimizer
    linux-optimizer --cortex    → modo Cortex Gaming Engine
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
    """Comando para iniciar en modo Cortex, o ``None`` si no está instalado."""
    if not cortex_available():
        return None
    return _session_command("--cortex")


def optimizer_command() -> list[str]:
    """Comando para iniciar en modo Linux Optimizer."""
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
        return False, f"No se pudo iniciar la aplicación: {exc}"
    return True, "Aplicación iniciada."


def launch_cortex() -> tuple[bool, str]:
    """Inicia la aplicación en modo Cortex (para scripts externos)."""
    command = cortex_command()
    if command is None:
        return False, (
            "No se encontró Cortex Gaming Engine. Reinstala Linux Optimizer "
            "o ejecuta la aplicación desde su carpeta completa.")
    ok, _message = _launch(command)
    if ok:
        return True, "Iniciando Cortex Gaming Engine…"
    return ok, _message


def launch_optimizer() -> tuple[bool, str]:
    """Inicia la aplicación en modo Optimizer (para scripts externos)."""
    ok, _message = _launch(optimizer_command())
    if ok:
        return True, "Iniciando Linux Optimizer…"
    return ok, _message
