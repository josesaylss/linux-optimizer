"""Ajustes seguros de kernel (vm.swappiness).

El cambio es idéntico al de un sysctl manual: confirmado por el usuario,
elevado con pkexec y siempre respaldado antes de aplicarse. La
persistencia opcional escribe un único archivo bien delimitado
(/etc/sysctl.d/90-linux-optimizer.conf) que la restauración elimina o
reemplaza por el original si ya existía.
"""

from __future__ import annotations

import os

from linux_optimizer.core.backup import BackupStore
from linux_optimizer.core.permissions import run_privileged

KERNEL_BACKUP_KIND = "kernel"
SYSCTL_CONF = "/etc/sysctl.d/90-linux-optimizer.conf"
PROC_SWAPPINESS = "/proc/sys/vm/swappiness"


def current_swappiness() -> int:
    """Valor actual de vm.swappiness (60 si no puede leerse)."""
    try:
        with open(PROC_SWAPPINESS, encoding="utf-8") as fh:
            return int(fh.read().strip())
    except (OSError, ValueError):
        return 60


def validate_swappiness(value: int) -> str:
    """Razón si el valor es inválido; "" si es válido."""
    if not isinstance(value, int) or not 0 <= value <= 100:
        return "El swappiness debe ser un entero entre 0 y 100"
    return ""


def conf_file_content(value: int) -> str:
    """Contenido del archivo de persistencia (solo valores internos)."""
    return (
        "# Generado por Linux Optimizer — no editar a mano\n"
        f"vm.swappiness = {value}\n"
    )


def apply_swappiness(
    value: int,
    backup: BackupStore,
    persist: bool = True,
) -> tuple[bool, str]:
    """Aplica vm.swappiness (runtime) y opcionalmente lo persiste.

    Crea siempre un snapshot con el valor previo y el archivo de
    persistencia anterior (si existía) para poder restaurar.
    """
    reason = validate_swappiness(value)
    if reason:
        return False, reason

    existed = os.path.exists(SYSCTL_CONF)
    previous = current_swappiness()
    backup.snapshot(
        kind=KERNEL_BACKUP_KIND,
        label=f"Swappiness previo: {previous}"
              + (f" (persistido en {SYSCTL_CONF})" if existed else ""),
        data={
            "swappiness": previous,
            "persisted_conf": existed,
        },
        file_paths=[SYSCTL_CONF] if existed else [],
    )

    rc, out, err = run_privileged(
        ["bash", "-c", f"echo '{value}' > {PROC_SWAPPINESS}"], timeout=30,
    )
    if rc != 0:
        return False, f"No se pudo aplicar el valor: {err.strip() or out.strip()}"

    messages = [f"vm.swappiness = {value} (aplicado en tiempo de ejecución)"]

    if persist:
        rc2, out2, err2 = run_privileged(
            ["bash", "-c", _write_conf_script(value)], timeout=30,
        )
        if rc2 != 0:
            return False, (
                f"Valor aplicado, pero no se pudo persistir: {err2.strip() or out2.strip()}"
            )
        messages.append(f"persistido en {SYSCTL_CONF}")

    return True, "; ".join(messages)


def restore_last_swappiness(backup: BackupStore) -> tuple[bool, str]:
    """Restaura el valor y el archivo de persistencia anteriores."""
    meta = backup.latest(KERNEL_BACKUP_KIND)
    if not meta:
        return False, "No hay respaldos de swappiness para restaurar"
    data = meta.get("data", {})
    previous = data.get("swappiness")
    had_conf = data.get("persisted_conf", False)

    # 1. Archivo de persistencia: restaurar el original o eliminar el nuestro.
    if had_conf:
        restored = backup.restore_files(meta["id"])
        if not restored:
            return False, "No se pudo restaurar el archivo de persistencia"
    else:
        rc, _out, err = run_privileged(
            ["bash", "-c", f"rm -f {SYSCTL_CONF}"], timeout=30,
        )
        if rc != 0:
            return False, f"No se pudo eliminar {SYSCTL_CONF}: {err.strip()}"

    # 2. Valor en runtime.
    if previous is not None:
        rc, _out, err = run_privileged(
            ["bash", "-c", f"echo '{previous}' > {PROC_SWAPPINESS}"], timeout=30,
        )
        if rc != 0:
            return False, f"Se restauró el archivo pero no el runtime: {err.strip()}"

    persist_msg = "conf restaurada" if had_conf else "conf eliminada"
    return True, f"Swappiness restaurado a {previous} ({persist_msg})"


def _write_conf_script(value: int) -> str:
    """Comando idempotente para escribir el conf (contenido interno fijo)."""
    safe_path = SYSCTL_CONF
    return (
        f"mkdir -p /etc/sysctl.d && "
        f"{{ echo '# Generado por Linux Optimizer — no editar a mano'; "
        f"echo 'vm.swappiness = {value}'; }} > {safe_path}"
    )
