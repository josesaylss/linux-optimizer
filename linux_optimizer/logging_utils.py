"""Configuración de registro compartida por la app y el proceso del HUD."""

from __future__ import annotations

import logging
import os
from pathlib import Path

from linux_optimizer import APP_NAME


def state_dir() -> Path:
    """Carpeta de estado de la aplicación (~/.local/state/LinuxOptimizer)."""
    base = os.environ.get("XDG_STATE_HOME") or Path.home() / ".local/state"
    return Path(base) / APP_NAME.replace(" ", "")


def setup_logging(announce: str | None = None) -> Path:
    """Registro a archivo para diagnosticar problemas reportados por el usuario."""
    directory = state_dir()
    directory.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        filename=str(directory / "app.log"),
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    if announce:
        logging.getLogger().info(announce)
    return directory
