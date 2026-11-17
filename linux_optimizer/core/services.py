"""Administración de servicios systemd con protección de servicios esenciales.

Toda acción (start/stop/restart/enable/disable) requiere:
  1. Confirmación del usuario en la UI (diálogo).
  2. Snapshot del estado previo en el almacén de respaldos.
  3. Elevación explícita con pkexec.

Los servicios esenciales (systemd, dbus, red, pantalla, autenticación...)
nunca pueden detenerse ni deshabilitarse desde la aplicación.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from linux_optimizer.core.backup import BackupStore
from linux_optimizer.core.permissions import run, run_privileged

SERVICES_BACKUP_KIND = "services"

# Subcadenas de unidades que la app se niega a detener/deshabilitar.
ESSENTIAL_KEYWORDS = (
    "systemd-",
    "systemd",
    "dbus",
    "networkmanager",
    "networkd",
    "resolved",
    "polkit",
    "logind",
    "getty",
    "udev",
    "display-manager",
    "sddm",
    "gdm",
    "lightdm",
    "lxdm",
    "wpa_supplicant",
    "iwd",
    "chronyd",
    "ntpd",
    "timesyncd",
    "firewalld",
    "ufw",
    "sshd",
    "sshd.socket",
    "udisks2",
    "upower",
    "accounts-daemon",
    "colord",
    "auditd",
    "rsyslog",
    "syslog-ng",
    "dbus-broker",
    "lvm2",
    "multipathd",
    "cryptdisks",
    "plymouth",
    "apparmor",
    "selinux",
    "tuned",
    "power-profiles-daemon",
    "postfix",
    "unbound",
    "nmb",
    "winbind",
)

ACTIONS = ("start", "stop", "restart", "enable", "disable")
DESTRUCTIVE_ACTIONS = ("stop", "disable")


@dataclass
class SystemdService:
    unit: str
    description: str
    load_state: str
    active_state: str
    sub_state: str
    enabled_state: str  # enabled | disabled | static | indirect | masked | ...

    @property
    def essential(self) -> bool:
        return is_essential(self.unit)

    @property
    def running(self) -> bool:
        return self.active_state == "active"


def is_essential(unit: str) -> bool:
    low = (unit or "").lower()
    return any(keyword in low for keyword in ESSENTIAL_KEYWORDS)


def is_action_allowed(unit: str, action: str) -> bool:
    """False si la app considera la acción peligrosa para esta unidad."""
    if not is_essential(unit):
        return True
    return action not in DESTRUCTIVE_ACTIONS


def action_blocked_reason(unit: str, action: str) -> str:
    if is_action_allowed(unit, action):
        return ""
    return (
        f"«{unit}» es un servicio esencial del sistema "
        f"y Linux Optimizer no permite {action == 'stop' and 'detenerlo' or 'deshabilitarlo'} "
        "para no romper el arranque, la red o la sesión gráfica."
    )


def systemd_available() -> bool:
    rc, _out, _err = run(["systemctl", "is-system-running"], timeout=10)
    # rc=1 significa "degraded" pero systemd está presente.
    return rc in (0, 1)


def _unit_file_states() -> dict[str, str]:
    rc, out, _err = run(
        ["systemctl", "list-unit-files", "--type=service",
         "--no-pager", "--no-legend"],
        timeout=20,
    )
    states: dict[str, str] = {}
    if rc != 0:
        return states
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 2:
            states[parts[0]] = parts[1]
    return states


def list_services() -> list[SystemdService]:
    """Lista de servicios systemd con su estado actual."""
    rc, out, err = run(
        ["systemctl", "list-units", "--type=service", "--all",
         "--no-pager", "--no-legend"],
        timeout=20,
    )
    services: list[SystemdService] = []
    if rc != 0:
        raise RuntimeError(err.strip() or "systemctl no está disponible")
    enabled = _unit_file_states()
    for line in out.splitlines():
        line = line.rstrip()
        if not line:
            continue
        match = re.match(r"(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s+(.*)", line)
        if not match:
            continue
        unit, load_state, active_state, sub_state, description = match.groups()
        services.append(SystemdService(
            unit=unit,
            description=description.strip(),
            load_state=load_state,
            active_state=active_state,
            sub_state=sub_state,
            enabled_state=enabled.get(unit, ""),
        ))
    services.sort(key=lambda s: (not s.essential, s.unit))
    return services


def unit_state(unit: str) -> dict:
    active_rc, active_out, _ = run(["systemctl", "is-active", unit], timeout=10)
    enabled_rc, enabled_out, _ = run(["systemctl", "is-enabled", unit], timeout=10)
    return {
        "active": active_out.strip() if active_rc == 0 else active_out.strip(),
        "enabled": enabled_out.strip() if enabled_rc in (0, 1) else "unknown",
        # is-enabled devuelve rc 1 para "disabled"/"static"; rc 4 si no existe.
    }


def snapshot_unit(backup: BackupStore, unit: str, label: str = "") -> str:
    """Guarda el estado actual de la unidad para poder restaurarlo."""
    state = unit_state(unit)
    return backup.snapshot(
        kind=SERVICES_BACKUP_KIND,
        label=label or f"Estado previo de {unit}",
        data={
            "unit": unit,
            "was_active": state["active"],
            "was_enabled": state["enabled"],
        },
    )


def restore_service_state(backup: BackupStore, snapshot_id: str) -> tuple[bool, str]:
    """Restaura el estado (activo/habilitado) que tenía una unidad."""
    meta = backup.load(snapshot_id)
    if not meta:
        return False, "El respaldo no existe"
    data = meta.get("data", {})
    unit = data.get("unit")
    if not unit:
        return False, "Respaldo sin unidad asociada"

    was_enabled = data.get("was_enabled", "unknown")
    was_active = data.get("was_active", "unknown")
    messages: list[str] = []

    if was_enabled == "enabled":
        rc, out, err = run_privileged(["systemctl", "enable", "--now", unit])
        if rc != 0:
            return False, err or out
        messages.append(f"{unit} habilitado y arrancado")
    else:
        rc, out, err = run_privileged(["systemctl", "disable", unit])
        if rc != 0 and "Failed to disable unit" not in (err + out):
            return False, err or out
        if was_active in ("active", "activating"):
            rc, out, err = run_privileged(["systemctl", "start", unit])
            if rc != 0:
                return False, err or out
            messages.append(f"{unit} deshabilitado y arrancado (estado original)")
        else:
            rc, _out, _err = run_privileged(["systemctl", "stop", unit])
            messages.append(f"{unit} deshabilitado y detenido (estado original)")
    return True, "; ".join(messages)


def apply_action(
    backup: BackupStore,
    unit: str,
    action: str,
) -> tuple[bool, str]:
    """Ejecuta una acción de systemd tras validar y crear respaldo.

    La confirmación previa es responsabilidad de la UI; aquí se valida
    que la acción sea segura según la lista de servicios esenciales.
    """
    if action not in ACTIONS:
        return False, f"Acción desconocida: {action}"
    reason = action_blocked_reason(unit, action)
    if reason:
        return False, reason

    if action in DESTRUCTIVE_ACTIONS:
        snapshot_unit(backup, unit, f"Antes de {action} {unit}")

    rc, out, err = run_privileged(["systemctl", action, unit], timeout=120)
    if rc != 0:
        if "not authorized" in err.lower() or "dismissed" in err.lower():
            return False, "Autenticación cancelada por el usuario."
        return False, err.strip() or out.strip() or f"systemctl {action} {unit} falló (rc={rc})"
    return True, f"{action} {unit}: OK"
