"""Registro de actividad propio de Cortex Gaming Engine.

Escribe en ``~/.local/state/LinuxOptimizer/cortex/activity.log`` y mantiene las
últimas entradas en memoria para mostrarlas en la ventana. No comparte el log
de Linux Optimizer.
"""

from __future__ import annotations

from collections import deque
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QObject, Signal

from cortex_engine.config import state_dir

MAX_ENTRIES = 500
LEVELS = {"INFO", "OK", "WARN", "ERROR"}


class ActivityLog(QObject):
    """Registro de actividad compartido por los módulos de Cortex."""

    changed = Signal()

    def __init__(self, path: Path | None = None, parent: QObject | None = None):
        super().__init__(parent)
        self.path = Path(path) if path is not None else state_dir() / "activity.log"
        self._entries: deque[str] = deque(maxlen=MAX_ENTRIES)
        self._load_tail()

    # ------------------------------------------------------------------

    def _load_tail(self) -> None:
        try:
            lines = self.path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            return
        for line in lines[-MAX_ENTRIES:]:
            if line.strip():
                self._entries.append(line)

    def log(self, message: str, level: str = "INFO") -> str:
        level = level.upper() if level.upper() in LEVELS else "INFO"
        line = (f"{datetime.now():%Y-%m-%d %H:%M:%S}  "
                f"{level:<5}  {message}")
        self._entries.append(line)
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")
        except OSError:
            pass
        self.changed.emit()
        return line

    def entries(self) -> list[str]:
        return list(self._entries)

    def clear(self) -> None:
        self._entries.clear()
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text("", encoding="utf-8")
        except OSError:
            pass
        self.changed.emit()
