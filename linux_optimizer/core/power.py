"""Administración de energía con detección de backend.

Orden de preferencia:
  1. power-profiles-daemon (powerprofilesctl) — Fedora/KDE, GNOME.
  2. TLP vía tuned-adm — Fedora/RHEL y derivadas con tuned.
  3. Governor de CPU (cpufreq) — siempre disponible como mínimo.

Los cambios de perfil requieren confirmación previa en la UI y se
elevan con pkexec, guardando un snapshot del perfil anterior.
"""

from __future__ import annotations

import glob
import os
from dataclasses import dataclass, field

from linux_optimizer.core.backup import BackupStore
from linux_optimizer.core.permissions import run, run_privileged

POWER_BACKUP_KIND = "power"

POWERPROFILES_PROFILES = ("performance", "balanced", "power-saver")


@dataclass
class PowerBackend:
    kind: str  # "power-profiles-daemon" | "tuned" | "governor" | "none"
    name: str
    profiles: list[str] = field(default_factory=list)
    current: str = ""

    @property
    def available(self) -> bool:
        return self.kind != "none"


def _detect_ppd() -> PowerBackend | None:
    rc, out, _ = run(["powerprofilesctl", "get"], timeout=10)
    if rc != 0:
        return None
    return PowerBackend(
        kind="power-profiles-daemon",
        name="power-profiles-daemon",
        profiles=list(POWERPROFILES_PROFILES),
        current=out.strip(),
    )


def _detect_tuned() -> PowerBackend | None:
    rc, out, _err = run(["tuned-adm", "active"], timeout=10)
    if rc != 0:
        return None
    current = ""
    for line in out.splitlines():
        if "current active profile" in line.lower():
            current = line.split(":")[-1].strip()
    _rc2, out2, _e = run(["tuned-adm", "list"], timeout=10)
    profiles = []
    for line in out2.splitlines():
        if " - " in line and line.startswith("-"):
            profiles.append(line[1:].split(" - ")[0].strip())
    return PowerBackend(kind="tuned", name="tuned-adm", profiles=profiles or [current], current=current)


def _detect_governor() -> PowerBackend | None:
    governors = available_governors()
    if not governors:
        return None
    return PowerBackend(
        kind="governor",
        name="governor de CPU (cpufreq)",
        profiles=governors,
        current=current_governor(),
    )


def detect_backend() -> PowerBackend:
    return _detect_ppd() or _detect_tuned() or _detect_governor() or PowerBackend(
        kind="none", name="ningún backend de energía disponible",
    )


def available_governors() -> list[str]:
    try:
        with open(
            "/sys/devices/system/cpu/cpu0/cpufreq/scaling_available_governors",
            encoding="utf-8",
        ) as fh:
            return [g for g in fh.read().split() if g]
    except OSError:
        return []


def current_governor() -> str:
    try:
        with open(
            "/sys/devices/system/cpu/cpu0/cpufreq/scaling_governor",
            encoding="utf-8",
        ) as fh:
            return fh.read().strip()
    except OSError:
        return ""


def set_profile(backup: BackupStore, backend: PowerBackend, profile: str) -> tuple[bool, str]:
    """Aplica un perfil de energía con snapshot previo (requiere pkexec)."""
    if not backend.available:
        return False, "No hay backend de energía disponible en este sistema"
    if profile not in backend.profiles:
        return False, f"El perfil «{profile}» no está disponible ({', '.join(backend.profiles)})"

    backup.snapshot(
        kind=POWER_BACKUP_KIND,
        label=f"Perfil de energía previo: {backend.current or 'desconocido'}",
        data={"kind": backend.kind, "profile": backend.current},
    )

    if backend.kind == "power-profiles-daemon":
        rc, out, err = run_privileged(["powerprofilesctl", "set", profile])
    elif backend.kind == "tuned":
        rc, out, err = run_privileged(["tuned-adm", "profile", profile])
    else:  # governor
        rc, out, err = set_governor(profile)
    if rc != 0:
        return False, err.strip() or out.strip() or f"Falló al aplicar el perfil (rc={rc})"
    return True, f"Perfil «{profile}» aplicado mediante {backend.name}"


def restore_last_power_profile(backup: BackupStore) -> tuple[bool, str]:
    meta = backup.latest(POWER_BACKUP_KIND)
    if not meta:
        return False, "No hay respaldos de energía para restaurar"
    data = meta.get("data", {})
    backend = PowerBackend(kind=data.get("kind", "none"), name="restauración",
                           profiles=[], current="")
    profile = data.get("profile", "")
    if not profile or backend.kind == "none":
        return False, "El respaldo no contiene un perfil válido"
    ok, msg = set_profile(backup, backend, profile)
    return ok, ("Restaurado. " + msg) if ok else msg


def battery_info() -> dict | None:
    try:
        import psutil
        battery = psutil.sensors_battery()
    except Exception:
        return None
    if battery is None:
        return None
    return {
        "percent": round(battery.percent, 1),
        "plugged": bool(battery.power_plugged),
        "secs_left": battery.secsleft,
    }


def set_governor(governor: str) -> tuple[int, str, str]:
    """Escribe el governor en todas las CPUs (requiere pkexec)."""
    paths = sorted(glob.glob("/sys/devices/system/cpu/cpu*/cpufreq/scaling_governor"))
    if not paths:
        return 1, "", "Este sistema no expone cpufreq (¿VM o CPU sin controlador?)"
    script = "; ".join(f"echo '{governor}' > {p}" for p in paths)
    return run_privileged(["bash", "-c", script], timeout=60)
