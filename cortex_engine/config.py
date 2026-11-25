"""Configuración propia de Cortex Gaming Engine.

Se guarda en ``~/.config/linux-optimizer/cortex.json`` (o ``$XDG_CONFIG_HOME``)
en Linux y en ``%APPDATA%\\linux-optimizer\\cortex.json`` en Windows. Es
totalmente independiente de la configuración de Linux Optimizer e incluye
exportación e importación para guardar/restaurar la configuración del usuario.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

from cortex_engine import APP_NAME, APP_VERSION
from linux_optimizer.core import platform_info

PROFILE_KEYS = ("eco", "balanced", "extreme")

DEFAULT_CONFIG = {
    "version": 1,
    "profile": "",
    "auto_detect_game": True,
    "monitor_interval_ms": 1500,
    "window_geometry": "",
}


def config_dir() -> Path:
    if platform_info.IS_WINDOWS:
        base = os.environ.get("APPDATA") or Path.home() / "AppData/Roaming"
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config"
    return Path(base) / "linux-optimizer"


def config_path() -> Path:
    return config_dir() / "cortex.json"


def state_dir() -> Path:
    if platform_info.IS_WINDOWS:
        base = os.environ.get("LOCALAPPDATA") or Path.home() / "AppData/Local"
    else:
        base = os.environ.get("XDG_STATE_HOME") or Path.home() / ".local/state"
    return Path(base) / "LinuxOptimizer" / "cortex"


class CortexConfig:
    """Pequeño almacén JSON con validación y exportación/importación."""

    def __init__(self, path: Path | None = None):
        self.path = Path(path) if path is not None else config_path()
        self.data: dict = dict(DEFAULT_CONFIG)
        self.load()

    # ------------------------------------------------------------------
    # Persistencia
    # ------------------------------------------------------------------

    def load(self) -> None:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raw = {}
        if not isinstance(raw, dict):
            raw = {}
        merged = dict(DEFAULT_CONFIG)
        for key in DEFAULT_CONFIG:
            if key in raw:
                merged[key] = raw[key]
        self.data = merged
        self._validate()

    def save(self) -> None:
        self._validate()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(
            json.dumps(self.data, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        os.replace(tmp, self.path)

    def _validate(self) -> None:
        if self.data.get("profile") not in ("", *PROFILE_KEYS):
            self.data["profile"] = ""
        try:
            interval = int(self.data.get("monitor_interval_ms", 1500))
        except (TypeError, ValueError):
            interval = 1500
        self.data["monitor_interval_ms"] = max(500, min(10000, interval))
        self.data["auto_detect_game"] = bool(
            self.data.get("auto_detect_game", True))
        geometry = self.data.get("window_geometry", "")
        self.data["window_geometry"] = geometry if isinstance(geometry, str) else ""

    # ------------------------------------------------------------------
    # Acceso
    # ------------------------------------------------------------------

    def get(self, key: str, default=None):
        return self.data.get(key, default)

    def set(self, key: str, value) -> None:
        self.data[key] = value
        self._validate()

    def reset(self) -> None:
        self.data = dict(DEFAULT_CONFIG)

    # ------------------------------------------------------------------
    # Guardar / restaurar configuración
    # ------------------------------------------------------------------

    def export_to(self, path: Path | str) -> Path:
        target = Path(path)
        payload = dict(self.data)
        payload["exported_by"] = f"{APP_NAME} {APP_VERSION}"
        payload["exported_at"] = datetime.now().isoformat(timespec="seconds")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        return target

    def import_from(self, path: Path | str) -> list[str]:
        """Carga otra configuración. Devuelve las claves aceptadas."""
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("El archivo no contiene una configuración válida.")
        accepted = [key for key in DEFAULT_CONFIG if key in raw]
        if not accepted:
            raise ValueError("El archivo no tiene ningún ajuste reconocible.")
        for key in accepted:
            # La geometría de la ventana no se importa entre equipos.
            if key == "window_geometry":
                continue
            self.data[key] = raw[key]
        self._validate()
        self.save()
        return [key for key in accepted if key != "window_geometry"]
