"""Guardado y restauración de configuraciones y del estado del sistema."""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

from cortex_engine.config import state_dir


class RestoreStore:
    """Guarda una instantánea de los valores originales antes de optimizar.

    El archivo se escribe de forma atómica. La instantánea **no se sobrescribe**
    al cambiar de perfil: así «Restaurar» siempre vuelve al estado original del
    equipo, no al del perfil anterior.
    """

    def __init__(self, path: Path | None = None):
        self.path = Path(path) if path is not None else state_dir() / "restore.json"

    def exists(self) -> bool:
        return self.path.exists()

    def save(self, snapshot: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = dict(snapshot)
        payload.setdefault("created", datetime.now().isoformat(timespec="seconds"))
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        os.replace(tmp, self.path)

    def load(self) -> dict | None:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return data if isinstance(data, dict) else None

    def clear(self) -> None:
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass

    def info(self) -> str:
        snapshot = self.load()
        if not snapshot:
            return "No hay valores originales guardados."
        created = snapshot.get("created", "fecha desconocida")
        return f"Valores originales guardados el {created}."
