"""Perfiles de Cortex en Windows mediante planes de energía nativos.

No usa pkexec ni bash: llama a ``powercfg`` directamente y guarda el GUID del
plan activo antes del primer cambio para poder restaurarlo exactamente.
"""

from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import QObject, Signal

from cortex_engine.cpu.windows import (
    PLAN_GUIDS,
    PLAN_TITLES,
    active_plan,
    plan_commands,
    set_plan,
)
from cortex_engine.profiles.manager import PROFILE_MAP, PROFILE_KEYS


class WindowsProfileManager(QObject):
    """Aplica ECO/BALANCED/EXTREME con el plan de energía de Windows."""

    changed = Signal()

    def __init__(self, config, activity, store):
        super().__init__()
        self.config = config
        self.activity = activity
        self.store = store

    # ------------------------------------------------------------------
    # Consultas compatibles con ProfileManager
    # ------------------------------------------------------------------

    def active(self) -> str:
        key = self.config.get("profile", "")
        return key if key in PROFILE_MAP else ""

    def preview(self, key: str) -> list[str]:
        return [label for _cmd_key, _command, label in plan_commands(key)]

    def notes(self, key: str) -> list[str]:
        return [
            "Windows: el perfil cambia el plan de energía del sistema "
            "(powercfg) y es reversible.",
        ]

    def has_snapshot(self) -> bool:
        return self.store.exists()

    def snapshot_info(self) -> str:
        return self.store.info()

    # ------------------------------------------------------------------

    def _label(self, key: str) -> str:
        return f"Plan de energía «{PLAN_TITLES[key]}»"

    def apply(self, key: str) -> tuple[list[str], list[str]]:
        if key not in PROFILE_KEYS:
            return [], [f"Perfil desconocido: {key}"]

        plan = active_plan()
        if not self.store.exists():
            if not plan.get("guid"):
                message = (
                    "No se pudo leer el plan de energía actual; por seguridad "
                    "no se ha cambiado nada.")
                self.activity.log(message, "ERROR")
                self.changed.emit()
                return [], [message]
            self.store.save({
                "created": datetime.now().isoformat(timespec="seconds"),
                "windows": {
                    "active_plan": plan["guid"],
                    "active_plan_name": plan.get("name", ""),
                },
            })
            self.activity.log(
                "Plan de energía original guardado antes de optimizar.")

        ok, message = set_plan(PLAN_GUIDS[key])
        if not ok:
            self.activity.log(
                f"No se pudo aplicar el perfil "
                f"{PROFILE_MAP[key].title}: {message}", "ERROR")
            self.changed.emit()
            return [], [f"{self._label(key)}: {message}"]

        self.config.set("profile", key)
        self.config.save()
        self.activity.log(
            f"Perfil {PROFILE_MAP[key].title} aplicado: {self._label(key)}.",
            "OK")
        self.changed.emit()
        return [self._label(key)], []

    def revert(self) -> tuple[list[str], list[str]]:
        snapshot = self.store.load()
        if not snapshot:
            return [], ["No hay valores originales guardados."]
        saved = (snapshot.get("windows") or {}).get("active_plan", "")
        if not saved:
            return [], ["La instantánea no contiene un plan de energía original."]

        ok, message = set_plan(saved)
        if not ok:
            self.activity.log(f"No se pudo restaurar el plan: {message}", "ERROR")
            self.changed.emit()
            return [], [f"Restaurar plan de energía: {message}"]

        self.store.clear()
        self.config.set("profile", "")
        self.config.save()
        name = (snapshot.get("windows") or {}).get("active_plan_name") or "original"
        label = f"Plan de energía «{name}» restaurado"
        self.activity.log(label + ".", "OK")
        self.changed.emit()
        return [label], []
