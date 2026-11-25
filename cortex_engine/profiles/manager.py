"""Perfiles propios de Cortex Gaming Engine: ECO, BALANCED y EXTREME.

Cada perfil se traduce en comandos concretos de los módulos de CPU, GPU y
memoria. Antes de aplicar el primero se guarda una instantánea de los valores
originales; «Restaurar» vuelve exactamente a ese estado.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from PySide6.QtCore import QObject, Signal

from linux_optimizer.core.cleaner import _parse_batch_output, build_batch_script
from linux_optimizer.core.permissions import is_cancelled, run_privileged


@dataclass(frozen=True)
class Profile:
    key: str
    title: str
    tagline: str
    description: str
    accent: str


PROFILES: tuple[Profile, ...] = (
    Profile(
        key="eco",
        title="ECO",
        tagline="Autonomía y silencio",
        description="Reduce consumo, temperatura y ruido. Pensado para jugar "
                    "con batería o en un portátil.",
        accent="#2fbf71",
    ),
    Profile(
        key="balanced",
        title="BALANCED",
        tagline="Rendimiento diario",
        description="Respuesta rápida sin disparar el consumo. El equilibrio "
                    "recomendado para la mayoría de equipos.",
        accent="#9be15d",
    ),
    Profile(
        key="extreme",
        title="EXTREME",
        tagline="Máximo rendimiento",
        description="CPU y GPU al máximo y memoria preparada para juegos "
                    "exigentes. Sube temperatura y consumo.",
        accent="#00ff9d",
    ),
)
PROFILE_MAP = {profile.key: profile for profile in PROFILES}
PROFILE_KEYS = tuple(PROFILE_MAP)


def apply_commands(
    commands: list[tuple[str, str, str]],
    timeout: float = 180.0,
) -> tuple[list[str], list[str]]:
    """Ejecuta comandos por lotes con **un solo** pkexec.

    Devuelve ``(etiquetas_aplicadas, fallos)``. Los comandos se agrupan en un
    único script para que el usuario solo vea un diálogo de autenticación.
    """
    if not commands:
        return [], ["No hay comandos que ejecutar."]
    rc, out, err = run_privileged(
        ["bash", "-c", build_batch_script(
            [(key, command) for key, command, _label in commands])],
        timeout=timeout,
    )
    parsed = _parse_batch_output(out)
    ok: list[str] = []
    failed: list[str] = []
    for command_key, _command, label in commands:
        command_rc = parsed.get(command_key)
        if command_rc == 0:
            ok.append(label)
        elif command_rc is None:
            if is_cancelled(err):
                failed.append(f"{label}: autenticación cancelada")
            else:
                failed.append(f"{label}: {err.strip() or f'pkexec rc={rc}'}")
        else:
            failed.append(f"{label}: comando falló (rc={command_rc})")
    return ok, failed


class ProfileManager(QObject):
    """Aplica y revierte perfiles con un único pkexec por operación."""

    changed = Signal()

    def __init__(self, config, activity, cpu, gpu, memory, store):
        super().__init__()
        self.config = config
        self.activity = activity
        self.cpu = cpu
        self.gpu = gpu
        self.memory = memory
        self.store = store

    # ------------------------------------------------------------------
    # Consultas
    # ------------------------------------------------------------------

    def active(self) -> str:
        key = self.config.get("profile", "")
        return key if key in PROFILE_MAP else ""

    def preview(self, key: str) -> list[str]:
        return [label for _key, _cmd, label in self._commands(key)]

    def notes(self, key: str) -> list[str]:
        if key not in PROFILE_MAP:
            return []
        return list(self.gpu.notes())

    def has_snapshot(self) -> bool:
        return self.store.exists()

    def snapshot_info(self) -> str:
        return self.store.info()

    # ------------------------------------------------------------------

    def _commands(self, key: str) -> list[tuple[str, str, str]]:
        return (self.cpu.commands(key)
                + self.gpu.commands(key)
                + self.memory.commands(key))

    def _build_snapshot(self) -> dict:
        return {
            "created": datetime.now().isoformat(timespec="seconds"),
            "cpu": self.cpu.snapshot(),
            "gpu": self.gpu.snapshot(),
            "memory": self.memory.snapshot(),
        }

    # ------------------------------------------------------------------
    # Aplicar
    # ------------------------------------------------------------------

    def apply(self, key: str) -> tuple[list[str], list[str]]:
        if key not in PROFILE_MAP:
            return [], [f"Perfil desconocido: {key}"]
        commands = self._commands(key)
        if not commands:
            message = ("Tu hardware no expone controles compatibles con este "
                       "perfil; no se ha cambiado nada.")
            self.activity.log(message, "WARN")
            return [], [message]

        # La instantánea original solo se crea una vez.
        if not self.store.exists():
            self.store.save(self._build_snapshot())
            self.activity.log("Valores originales guardados antes de optimizar.")

        ok, failed = apply_commands(commands)

        if ok:
            self.config.set("profile", key)
            self.config.save()
            self.activity.log(
                f"Perfil {PROFILE_MAP[key].title} aplicado: "
                + "; ".join(ok), "OK")
        else:
            self.activity.log(
                f"No se pudo aplicar el perfil {PROFILE_MAP[key].title}.", "ERROR")
        self.changed.emit()
        return ok, failed

    # ------------------------------------------------------------------
    # Restaurar
    # ------------------------------------------------------------------

    def revert(self) -> tuple[list[str], list[str]]:
        snapshot = self.store.load()
        if not snapshot:
            return [], ["No hay valores originales guardados."]
        commands = (self.cpu.revert_commands(snapshot.get("cpu") or {})
                    + self.gpu.revert_commands(snapshot.get("gpu") or {})
                    + self.memory.revert_commands(snapshot.get("memory") or {}))
        if not commands:
            self.store.clear()
            self.activity.log("No había cambios del sistema que restaurar.", "WARN")
            self.changed.emit()
            return [], ["No había cambios del sistema que restaurar."]

        ok, failed = apply_commands(commands)

        if ok and not failed:
            self.store.clear()
            self.config.set("profile", "")
            self.config.save()
            self.activity.log("Configuración original del sistema restaurada.", "OK")
        elif ok:
            self.activity.log(
                "Restauración parcial: algunos valores no se pudieron cambiar.",
                "WARN")
        else:
            self.activity.log("No se pudo restaurar la configuración original.",
                              "ERROR")
        self.changed.emit()
        return ok, failed
