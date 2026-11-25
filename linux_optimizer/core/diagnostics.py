"""Herramientas de diagnóstico: solo lectura, sin modificar el sistema."""

from __future__ import annotations

import os
import platform
import re
from dataclasses import dataclass

import psutil

from linux_optimizer.core import hardware, platform_info
from linux_optimizer.core.permissions import run


@dataclass
class CheckResult:
    name: str
    severity: str  # ok | info | warn | crit
    detail: str

    @property
    def icon(self) -> str:
        return {"ok": "✔", "info": "ℹ", "warn": "⚠", "crit": "✖"}.get(self.severity, "ℹ")


SEVERITY_ORDER = {"crit": 0, "warn": 1, "ok": 2, "info": 3}


def _fmt_bytes(num: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(num) < 1024 or unit == "TB":
            return f"{num:,.1f} {unit}"
        num /= 1024
    return f"{num:,.1f} TB"


# ----------------------------------------------------------------------------
# Comprobaciones individuales
# ----------------------------------------------------------------------------

def check_boot_time() -> CheckResult:
    rc, out, _err = run(["systemd-analyze"], timeout=15)
    if rc != 0:
        return CheckResult("Tiempo de arranque", "info",
                           "systemd-analyze no disponible")
    line = out.strip().splitlines()[0] if out.strip() else ""
    return CheckResult("Tiempo de arranque", "ok", line or "sin datos")


def check_failed_units() -> CheckResult:
    rc, out, _err = run(
        ["systemctl", "--failed", "--no-pager", "--no-legend"], timeout=15,
    )
    lines = [l for l in out.splitlines() if l.strip()]
    if rc != 0:
        return CheckResult("Servicios con fallo", "info", "systemctl no disponible")
    if not lines:
        return CheckResult("Servicios con fallo", "ok", "Ninguna unidad ha fallado")
    return CheckResult("Servicios con fallo", "crit",
                       f"{len(lines)} unidad(es) en fallo:\n" + "\n".join(lines))


def check_journal_errors() -> CheckResult:
    rc, out, _err = run(
        ["journalctl", "-p", "3", "-b", "--no-pager", "-n", "15"], timeout=20,
    )
    lines = [l for l in out.splitlines() if l.strip()]
    if rc != 0:
        return CheckResult("Errores del registro (journal)", "info",
                           "Requiere estar en el grupo systemd-journal o ejecutar con privilegios")
    if not lines:
        return CheckResult("Errores del registro (journal)", "ok",
                           "Sin errores de prioridad ≤3 en este arranque")
    return CheckResult("Errores del registro (journal)", "warn",
                       "Últimos errores de este arranque:\n" + "\n".join(lines))


def check_disk_usage() -> CheckResult:
    details = []
    worst = "ok"
    for disk in hardware.detect_disks():
        if disk.total <= 0:
            continue
        pct = disk.used * 100 / disk.total
        details.append(
            f"{disk.mount} ({disk.device}, {disk.fstype}): "
            f"{pct:.1f}% usado · libre {_fmt_bytes(disk.free)}"
        )
        if pct >= 95:
            worst = "crit"
        elif pct >= 85 and worst != "crit":
            worst = "warn"
    if not details:
        return CheckResult("Espacio en disco", "info", "Sin particiones montadas legibles")
    return CheckResult("Espacio en disco", worst, "\n".join(details))


def check_memory() -> CheckResult:
    vm = psutil.virtual_memory()
    swap = psutil.swap_memory()
    detail = (
        f"RAM: {vm.percent:.1f}% usado ({_fmt_bytes(vm.used)} de {_fmt_bytes(vm.total)})\n"
        f"Swap: {swap.percent:.1f}% usado ({_fmt_bytes(swap.used)} de {_fmt_bytes(swap.total)})"
    )
    severity = "ok" if vm.percent < 85 else ("warn" if vm.percent < 95 else "crit")
    return CheckResult("Memoria", severity, detail)


def check_temperature() -> CheckResult:
    temps = hardware.detect_temperatures()
    if not temps:
        return CheckResult("Temperatura", "info",
                           "Sin sensores accesibles (normal en VMs o hardware sin k10temp/coretemp)")
    hot = [(name, t) for name, t in temps if t >= 85]
    max_name, max_temp = max(temps, key=lambda item: item[1])
    if hot or max_temp >= 90:
        severity = "crit" if max_temp >= 100 else "warn"
        detail = f"Temperatura máxima {max_temp:.0f} °C ({max_name})"
    else:
        severity = "ok"
        detail = f"Temperatura máxima {max_temp:.0f} °C ({max_name}) · todo correcto"
    return CheckResult("Temperatura", severity, detail)


def check_swappiness() -> CheckResult:
    try:
        with open("/proc/sys/vm/swappiness", encoding="utf-8") as fh:
            value = int(fh.read().strip())
    except (OSError, ValueError):
        return CheckResult("Swappiness", "info", "No se pudo leer /proc/sys/vm/swappiness")
    note = {
        10: "valor agresivo para escritorio/juegos (bueno si tienes suficiente RAM)",
        60: "valor por defecto de Linux",
    }.get(value, "")
    return CheckResult("Swappiness", "ok", f"vm.swappiness = {value}" + (f" · {note}" if note else ""))


def check_cpu_governor() -> CheckResult:
    try:
        with open("/sys/devices/system/cpu/cpu0/cpufreq/scaling_governor",
                  encoding="utf-8") as fh:
            governor = fh.read().strip()
    except OSError:
        return CheckResult("Governor de CPU", "info",
                           "cpufreq no disponible (¿máquina virtual?)")
    severity = "ok" if governor in ("performance", "schedutil", "ondemand") else "warn"
    return CheckResult("Governor de CPU", severity, f"Governor activo: {governor}")


def check_kernel_logs() -> CheckResult:
    rc, out, err = run(["dmesg", "--level=err,warn", "--color=never", "-n", "15"], timeout=15)
    lines = [l for l in out.splitlines() if l.strip()]
    if rc != 0:
        return CheckResult("Mensajes del kernel", "info",
                           "dmesg restringido (requiere privilegios o grupo especial)" if "denied" in err.lower() or not lines else err.strip())
    if not lines:
        return CheckResult("Mensajes del kernel", "ok", "Sin errores ni advertencias recientes")
    return CheckResult("Mensajes del kernel", "warn",
                       "Últimos avisos del kernel:\n" + "\n".join(lines))


def check_system_summary() -> CheckResult:
    if platform_info.IS_WINDOWS:
        logical = psutil.cpu_count(logical=True) or 0
        detail = (
            f"Windows {platform.release()} · {platform.machine()} · "
            f"{logical} CPUs lógicas")
        return CheckResult("Sistema", "ok", detail)
    try:
        uname = platform.uname()
        detail = f"{uname.system} {uname.release} · {uname.machine} · {len(os.sched_getaffinity(0))} CPUs visibles"
        return CheckResult("Sistema", "ok", detail)
    except Exception as exc:  # pragma: no cover
        return CheckResult("Sistema", "info", f"No se pudo leer: {exc}")


def check_power_plan() -> CheckResult:
    """Plan de energía activo (solo Windows); Cortex lo usa para los perfiles."""
    rc, out, err = run(["powercfg", "/getactivescheme"], timeout=15)
    if rc != 0:
        return CheckResult("Plan de energía", "info",
                           err.strip() or "powercfg no disponible")
    match = re.search(
        r"\(([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
        r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12})\)", out)
    if match:
        name = out[:match.start()].rsplit(":", 1)[-1].strip()
    else:
        match = re.search(r"\(([^)]*)\)", out)
        name = match.group(1).strip() if match else out.strip()
    return CheckResult("Plan de energía", "ok",
                       f"Plan activo: {name or 'desconocido'}")


# ----------------------------------------------------------------------------
# Conjunto completo
# ----------------------------------------------------------------------------

def run_checks() -> list[CheckResult]:
    if platform_info.IS_WINDOWS:
        checks = [
            check_system_summary(),
            check_power_plan(),
            check_disk_usage(),
            check_memory(),
            check_temperature(),
        ]
    else:
        checks = [
            check_system_summary(),
            check_boot_time(),
            check_failed_units(),
            check_disk_usage(),
            check_memory(),
            check_temperature(),
            check_cpu_governor(),
            check_swappiness(),
            check_journal_errors(),
            check_kernel_logs(),
        ]
    checks.sort(key=lambda c: SEVERITY_ORDER.get(c.severity, 3))
    return checks


def format_report(checks: list[CheckResult]) -> str:
    lines = ["Linux Optimizer — Informe de diagnóstico", ""]
    for check in checks:
        lines.append(f"[{check.severity.upper():4}] {check.icon} {check.name}")
        for detail_line in check.detail.splitlines():
            lines.append(f"       {detail_line}")
        lines.append("")
    return "\n".join(lines)
