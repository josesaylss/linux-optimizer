"""Modo Gaming: optimizaciones temporales y reversibles.

Cada acción declara si necesita privilegios y cómo revertirse.
La UI pide confirmación antes de aplicar cualquier cambio y guarda
un snapshot del estado previo para poder restaurarlo.
"""

from __future__ import annotations

import glob
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from linux_optimizer.core import cleaner, hardware
from linux_optimizer.core.backup import BackupStore
from linux_optimizer.core.permissions import run, run_privileged

GAMING_BACKUP_KIND = "gaming"


@dataclass
class GamingAction:
    key: str
    title: str
    description: str
    needs_root: bool
    apply: object            # Callable[[], tuple[bool, str]]
    revert: object | None = None  # Callable[[], tuple[bool, str]] | None
    applied: bool = False
    supported: bool = True
    unsupported_reason: str = ""


class GamingManager:
    def __init__(self, backup: BackupStore, app_cache_dir: str | None = None):
        self.backup = backup
        self.app_cache_dir = app_cache_dir
        self.actions: list[GamingAction] = []
        self._saved_governors: dict[str, str] = {}
        self._stopped_units: list[str] = []
        self._build_actions()

    # ------------------------------------------------------------------
    # Construcción de acciones disponibles
    # ------------------------------------------------------------------

    def _build_actions(self) -> None:
        self.actions = [
            self._action_clean_cache(),
            self._action_governor(),
            self._action_stop_bluetooth(),
            self._action_stop_cups(),
            self._action_stop_avahi(),
        ]

    def _action_clean_cache(self) -> GamingAction:
        cache = str(Path.home() / ".cache")

        def apply():
            result = cleaner.delete_contents(
                [cache], exclude=[self.app_cache_dir],
            )
            if result.error:
                return False, result.error
            return True, f"Caché de usuario liberada: {_fmt(result.freed)}"

        return GamingAction(
            key="clean_cache",
            title="Vaciar caché de usuario (~/.cache)",
            description="Libera memoria de disco y reduce I/O al jugar. "
                        "Los datos se regeneran solos.",
            needs_root=False,
            apply=apply,
            revert=None,
        )

    def _action_governor(self) -> GamingAction:
        paths = sorted(glob.glob("/sys/devices/system/cpu/cpu*/cpufreq/scaling_governor"))
        if not paths:
            action = GamingAction(
                key="cpu_governor",
                title="CPU en modo rendimiento",
                description="Pone el governor de CPU en «performance» durante la sesión de juego.",
                needs_root=True,
                apply=lambda: (False, "No disponible"),
            )
            action.supported = False
            action.unsupported_reason = "Este sistema no expone cpufreq (¿VM?)"
            return action
        governors = []
        try:
            with open("/sys/devices/system/cpu/cpu0/cpufreq/scaling_available_governors",
                      encoding="utf-8") as fh:
                governors = fh.read().split()
        except OSError:
            pass
        action = GamingAction(
            key="cpu_governor",
            title="CPU en modo rendimiento",
            description="Pone el governor de CPU en «performance» durante la sesión de juego.",
            needs_root=True,
            apply=self._apply_governor,
            revert=self._revert_governor,
        )
        if "performance" not in governors:
            action.supported = False
            action.unsupported_reason = (
                f"Governors disponibles: {', '.join(governors) or 'desconocidos'}"
            )
        return action

    def _apply_governor(self) -> tuple[bool, str]:
        paths = sorted(glob.glob("/sys/devices/system/cpu/cpu*/cpufreq/scaling_governor"))
        # Guardar el estado actual (aplicación + snapshot en disco).
        self._saved_governors = {}
        for path in paths:
            try:
                with open(path, encoding="utf-8") as fh:
                    self._saved_governors[path] = fh.read().strip()
            except OSError:
                continue
        self.backup.snapshot(
            kind=GAMING_BACKUP_KIND,
            label="Governor de CPU antes del modo gaming",
            data={"governors": self._saved_governors},
        )
        script = "; ".join(
            f"echo 'performance' > {p}" for p in paths
        )
        rc, out, err = run_privileged(["bash", "-c", script], timeout=60)
        if rc != 0:
            return False, err.strip() or out.strip() or "pkexec falló"
        return True, f"Governor «performance» aplicado en {len(paths)} CPUs"

    def _revert_governor(self) -> tuple[bool, str]:
        if not self._saved_governors:
            return False, "No hay governor guardado que restaurar"
        script = "; ".join(
            f"echo '{gov}' > {path}" for path, gov in self._saved_governors.items()
        )
        rc, out, err = run_privileged(["bash", "-c", script], timeout=60)
        if rc != 0:
            return False, err.strip() or out.strip()
        saved = self._saved_governors
        self._saved_governors = {}
        values = sorted(set(saved.values()))
        return True, f"Governor restaurado: {', '.join(values)}"

    def _unit_action(self, key: str, unit: str, title: str, description: str) -> GamingAction:
        rc_active, active_out, _ = run(["systemctl", "is-active", unit], timeout=10)
        exists = rc_active in (0, 1, 3)  # active/inactive/failed => la unidad existe

        def apply():
            self.backup.snapshot(
                kind=GAMING_BACKUP_KIND,
                label=f"Antes de detener {unit}",
                data={"unit": unit},
            )
            rc, out, err = run_privileged(["systemctl", "stop", unit], timeout=60)
            if rc != 0:
                return False, err.strip() or out.strip()
            if unit not in self._stopped_units:
                self._stopped_units.append(unit)
            return True, f"{unit} detenido"

        def revert():
            if unit not in self._stopped_units:
                return True, f"{unit} no estaba detenido por el modo gaming"
            rc, out, err = run_privileged(["systemctl", "start", unit], timeout=60)
            if rc != 0:
                return False, err.strip() or out.strip()
            self._stopped_units.remove(unit)
            return True, f"{unit} reiniciado"

        action = GamingAction(
            key=key,
            title=title,
            description=description,
            needs_root=True,
            apply=apply,
            revert=revert,
        )
        if not exists:
            action.supported = False
            action.unsupported_reason = f"El servicio {unit} no existe en este sistema"
        return action

    def _action_stop_bluetooth(self) -> GamingAction:
        return self._unit_action(
            "stop_bluetooth",
            "bluetooth.service",
            "Detener Bluetooth (temporal)",
            "Libera interrupciones y procesos de fondo. Se reinicia al salir del modo gaming.",
        )

    def _action_stop_cups(self) -> GamingAction:
        return self._unit_action(
            "stop_cups",
            "cups.service",
            "Detener impresión (CUPS, temporal)",
            "El spooler de impresión no se necesita mientras juegas. Se reinicia al revertir.",
        )

    def _action_stop_avahi(self) -> GamingAction:
        return self._unit_action(
            "stop_avahi",
            "avahi-daemon.service",
            "Detener descubrimiento de red (Avahi, temporal)",
            "Reduce tráfico y latencia de red de fondo. Se reinicia al revertir.",
        )

    # ------------------------------------------------------------------
    # Aplicación / reversión
    # ------------------------------------------------------------------

    def apply(self, keys: list[str]) -> tuple[list[str], list[str]]:
        """Aplica las acciones cuyas claves se pasan. Devuelve (éxitos, errores)."""
        ok: list[str] = []
        failed: list[str] = []
        for action in self.actions:
            if action.key not in keys or not action.supported:
                continue
            success, message = action.apply()
            if success:
                action.applied = True
                ok.append(f"{action.title}: {message}")
            else:
                failed.append(f"{action.title}: {message}")
        return ok, failed

    def revert_all(self) -> tuple[list[str], list[str]]:
        ok: list[str] = []
        failed: list[str] = []
        for action in self.actions:
            if not action.applied or action.revert is None:
                continue
            success, message = action.revert()
            if success:
                action.applied = False
                ok.append(f"{action.title}: {message}")
            else:
                failed.append(f"{action.title}: {message}")
        return ok, failed

    def gamemode_installed(self) -> bool:
        return shutil.which("gamemoded") is not None or shutil.which("gamemode") is not None

    def hardware_summary(self) -> str:
        cpu = hardware.detect_cpu()
        gpus = hardware.detect_gpus()
        gpu_text = ", ".join(g.short() for g in gpus) if gpus else "GPU no detectada"
        return f"{cpu.model} · {gpu_text}"


def _fmt(num: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(num) < 1024 or unit == "TB":
            return f"{num:,.1f} {unit}"
        num /= 1024
    return f"{num:,.1f} TB"
