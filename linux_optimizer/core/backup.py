"""Copias de seguridad y restauración de configuraciones.

Los respaldos viven en ~/.local/share/LinuxOptimizer/backups/<id>/ con:
  - metadata.json : tipo, etiqueta, fecha, datos JSON y lista de archivos
  - files/        : copia exacta de los archivos originales (permisos incluidos)

Cualquier acción que modifique el sistema (servicios, perfiles de energía,
governor de CPU) crea primero un snapshot para poder restaurar los cambios.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import time
from pathlib import Path

from linux_optimizer import APP_NAME


def default_backup_dir() -> Path:
    base = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    return Path(base) / APP_NAME.replace(" ", "") / "backups"


class BackupStore:
    def __init__(self, base_dir: Path | None = None):
        self.base_dir = Path(base_dir) if base_dir else default_backup_dir()
        self.base_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Creación
    # ------------------------------------------------------------------

    def snapshot(
        self,
        kind: str,
        label: str,
        data: dict | None = None,
        file_paths: list[str] | None = None,
    ) -> str:
        """Crea un snapshot y devuelve su id (timestamp + kind + ordinal)."""
        timestamp = time.strftime('%Y%m%d-%H%M%S')
        snapshot_id = f"{timestamp}-{kind}"
        # Garantiza unicidad aunque haya varios snapshots en el mismo segundo.
        serial = 0
        while (self.base_dir / snapshot_id).exists():
            serial += 1
            snapshot_id = f"{timestamp}-{kind}-{serial}"
        snap_dir = self.base_dir / snapshot_id
        files_dir = snap_dir / "files"
        files_dir.mkdir(parents=True, exist_ok=False)

        stored: list[dict] = []
        for original in file_paths or []:
            src = Path(original)
            if not src.is_file():
                continue
            # Nombre plano: /etc/foo/bar.conf -> etc__foo__bar.conf
            stored_name = str(src).strip("/").replace("/", "__")
            dst = files_dir / stored_name
            try:
                shutil.copy2(src, dst)
            except OSError:
                continue
            stored.append({
                "original": str(src),
                "stored": stored_name,
                "sha256": _sha256(src),
            })

        metadata = {
            "id": snapshot_id,
            "kind": kind,
            "label": label,
            "timestamp": time.time(),
            "created": time.strftime("%Y-%m-%d %H:%M:%S"),
            "data": data or {},
            "files": stored,
        }
        with open(snap_dir / "metadata.json", "w", encoding="utf-8") as fh:
            json.dump(metadata, fh, indent=2, ensure_ascii=False)
        return snapshot_id

    # ------------------------------------------------------------------
    # Consulta
    # ------------------------------------------------------------------

    def list_snapshots(self, kind: str | None = None) -> list[dict]:
        result: list[dict] = []
        if not self.base_dir.is_dir():
            return result
        for entry in self.base_dir.iterdir():
            meta_path = entry / "metadata.json"
            if not entry.is_dir() or not meta_path.is_file():
                continue
            try:
                with open(meta_path, encoding="utf-8") as fh:
                    meta = json.load(fh)
            except (OSError, json.JSONDecodeError):
                continue
            if kind and meta.get("kind") != kind:
                continue
            result.append(meta)
        result.sort(key=lambda m: m.get("timestamp", 0), reverse=True)
        return result

    def latest(self, kind: str) -> dict | None:
        snapshots = self.list_snapshots(kind)
        return snapshots[0] if snapshots else None

    def load(self, snapshot_id: str) -> dict | None:
        meta_path = self.base_dir / snapshot_id / "metadata.json"
        try:
            with open(meta_path, encoding="utf-8") as fh:
                return json.load(fh)
        except (OSError, json.JSONDecodeError):
            return None

    def delete(self, snapshot_id: str) -> bool:
        """Elimina físicamente un snapshot y sus respaldos de archivos."""
        # Barrera de seguridad: solo nombres de carpeta directos del almacén
        # (sin rutas, sin puntos especiales, sin vacío).
        if (
            not snapshot_id
            or "/" in snapshot_id
            or "\\" in snapshot_id
            or snapshot_id in (".", "..")
        ):
            return False
        snapshot_dir = self.base_dir / snapshot_id
        if snapshot_dir.parent != self.base_dir or not snapshot_dir.is_dir():
            return False
        shutil.rmtree(snapshot_dir, ignore_errors=True)
        return not snapshot_dir.exists()

    # ------------------------------------------------------------------
    # Restauración
    # ------------------------------------------------------------------

    def restore_files(self, snapshot_id: str) -> list[str]:
        """Restaura los archivos del snapshot y devuelve las rutas tocadas."""
        meta = self.load(snapshot_id)
        if not meta:
            return []
        files_dir = self.base_dir / snapshot_id / "files"
        restored: list[str] = []
        for entry in meta.get("files", []):
            src = files_dir / entry["stored"]
            dst = Path(entry["original"])
            if not src.is_file():
                continue
            try:
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
                restored.append(str(dst))
            except OSError:
                continue
        return restored


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(65536), b""):
                digest.update(chunk)
    except OSError:
        return ""
    return digest.hexdigest()
