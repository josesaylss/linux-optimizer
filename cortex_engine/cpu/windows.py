"""CPU y planes de energía de Windows para Cortex.

Windows no expone governors de cpufreq; el equivalente seguro y reversible es
cambiar el plan de energía activo con ``powercfg``. Se usan los GUID oficiales
que existen en Windows 10 y 11.
"""

from __future__ import annotations

import re
import subprocess

PLAN_GUIDS = {
    "eco": "a1841308-3541-4fab-bc81-f71556f20b4a",       # Ahorro de energía
    "balanced": "381b4222-f694-41f0-9685-ff5bb260df2e",  # Equilibrado
    "extreme": "8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c",   # Alto rendimiento
}

PLAN_TITLES = {
    "eco": "Ahorro de energía",
    "balanced": "Equilibrado",
    "extreme": "Alto rendimiento",
}


def _run(command: list[str], timeout: float = 20.0) -> tuple[int, str, str]:
    try:
        proc = subprocess.run(command, capture_output=True, text=True,
                              timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 1, "", str(exc)
    return proc.returncode, proc.stdout or "", proc.stderr or ""


def active_plan() -> dict:
    """Devuelve ``{"guid", "name"}`` del plan de energía activo."""
    rc, out, err = _run(["powercfg", "/getactivescheme"])
    if rc != 0:
        return {"guid": "", "name": "", "error": err.strip()}
    match = re.search(
        r"([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
        r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12})\s*\(([^)]*)\)", out)
    if not match:
        return {"guid": "", "name": "", "error": "No se pudo interpretar powercfg"}
    return {"guid": match.group(1).lower(), "name": match.group(2).strip()}


def plan_commands(profile: str) -> list[tuple[str, str, str]]:
    guid = PLAN_GUIDS.get(profile)
    if not guid:
        return []
    title = PLAN_TITLES[profile]
    return [(
        "windows_power_plan",
        f"powercfg /setactive {guid}",
        f"Plan de energía «{title}»",
    )]


def set_plan(guid: str) -> tuple[bool, str]:
    if not guid:
        return False, "No hay un plan de energía guardado."
    rc, _out, err = _run(["powercfg", "/setactive", guid])
    if rc != 0:
        detail = err.strip() or f"powercfg rc={rc}"
        return False, (
            f"{detail}\n\nSi Windows lo bloquea, ejecuta la aplicación como "
            "administrador.")
    return True, "Plan de energía aplicado."
