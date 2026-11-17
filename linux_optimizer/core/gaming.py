"""Modo Gaming: optimizaciones temporales y reversibles.

Cada acción declara si necesita privilegios y cómo revertirse. Las acciones
root se agrupan y se ejecutan en UN solo diálogo de pkexec (la UI pide
confirmación antes y el estado previo queda respaldado).
"""

from __future__ import annotations

import glob
import logging
import shutil
from dataclasses import dataclass
from pathlib import Path

from linux_optimizer.core import cleaner, hardware
from linux_optimizer.core.backup import BackupStore
from linux_optimizer.core.permissions import run, run_privileged
from linux_optimizer.core.cleaner import build_batch_script, _parse_batch_output

GAMING_BACKUP_KIND = "gaming"
log = logging.getLogger("LinuxOptimizer.gaming")


@dataclass
class GamingAction:
    key: str
    title: str
    description: str
    needs_root: bool
    # Acciones de usuario (sin root): se ejecutan en el proceso actual.
    apply: object | None = None           # Callable[[], tuple[bool, str]]
    # Acciones root: comando shell por lotes + pasos de estado en Python.
    root_command: object | None = None    # Callable[[], str]
    revert_command: object | None = None  # Callable[[], str]
    pre_apply: object | None = None       # Callable[[], str | None] (snapshot previo)
    mark_applied: object | None = None    # Callable[[], str]
    mark_reverted: object | None = None   # Callable[[], str]
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
            self._action_amdgpu_performance(),
            self._action_swappiness(),
            self._action_drop_caches(),
            self._action_stop_bluetooth(),
            self._action_stop_cups(),
            self._action_stop_avahi(),
        ]

    def _action_clean_cache(self) -> GamingAction:
        cache = str(Path.home() / ".cache")

        def apply():
            exclude = [self.app_cache_dir] if self.app_cache_dir else []
            result = cleaner.delete_contents([cache], exclude=exclude)
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
        )

    def _action_governor(self) -> GamingAction:
        paths = sorted(glob.glob("/sys/devices/system/cpu/cpu*/cpufreq/scaling_governor"))
        action = GamingAction(
            key="cpu_governor",
            title="CPU en modo rendimiento",
            description="Pone el governor de CPU en «performance» durante la sesión de juego.",
            needs_root=True,
        )
        if not paths:
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
        if "performance" not in governors:
            action.supported = False
            action.unsupported_reason = (
                f"Governors disponibles: {', '.join(governors) or 'desconocidos'}"
            )
            return action

        def pre_apply() -> str | None:
            """Guarda el governor actual (lectura sin root) + snapshot en disco."""
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
            return None

        def root_command() -> str:
            return "; ".join(
                f"echo 'performance' > {p}" for p in paths
            )

        def mark_applied() -> str:
            current = _read_governor(paths[0])
            if current != "performance":
                return f"⚠ El governor quedó en «{current or 'desconocido'}»"
            return f"Governor «performance» aplicado en {len(paths)} CPUs"

        def revert_command() -> str:
            if not self._saved_governors:
                return "true"
            return "; ".join(
                f"echo '{gov}' > {path}" for path, gov in self._saved_governors.items()
            )

        def mark_reverted() -> str:
            values = sorted(set(self._saved_governors.values()))
            self._saved_governors = {}
            return f"Governor restaurado: {', '.join(values) or 'original'}"

        action.pre_apply = pre_apply
        action.root_command = root_command
        action.mark_applied = mark_applied
        action.revert_command = revert_command
        action.mark_reverted = mark_reverted
        return action

    def _unit_action(self, key: str, unit: str, title: str, description: str) -> GamingAction:
        rc_active, _active_out, _ = run(["systemctl", "is-active", unit], timeout=10)
        exists = rc_active in (0, 1, 3)  # active/inactive/failed => la unidad existe

        def pre_apply() -> str | None:
            self.backup.snapshot(
                kind=GAMING_BACKUP_KIND,
                label=f"Antes de detener {unit}",
                data={"unit": unit},
            )
            return None

        def root_command() -> str:
            return f"systemctl stop {unit}"

        def mark_applied() -> str:
            if unit not in self._stopped_units:
                self._stopped_units.append(unit)
            return f"{unit} detenido"

        def revert_command() -> str:
            if unit not in self._stopped_units:
                return "true"
            return f"systemctl start {unit}"

        def mark_reverted() -> str:
            if unit in self._stopped_units:
                self._stopped_units.remove(unit)
            return f"{unit} reiniciado"

        action = GamingAction(
            key=key,
            title=title,
            description=description,
            needs_root=True,
            pre_apply=pre_apply,
            root_command=root_command,
            mark_applied=mark_applied,
            revert_command=revert_command,
            mark_reverted=mark_reverted,
        )
        if not exists:
            action.supported = False
            action.unsupported_reason = f"El servicio {unit} no existe en este sistema"
        return action

    def _action_amdgpu_performance(self) -> GamingAction:
        paths = sorted(glob.glob(
            "/sys/class/drm/card*/device/power_dpm_force_performance_level"))
        action = GamingAction(
            key="amdgpu_perf",
            title="GPU AMD en rendimiento alto",
            description="Fuerza el nivel de energía de la GPU AMD a «high» durante el juego "
                        "en vez de la gestión automática (revertible).",
            needs_root=True,
        )
        if not paths:
            action.supported = False
            action.unsupported_reason = "No hay GPU AMD con controlador amdgpu"
            return action
        self._saved_dpm: dict[str, str] = getattr(self, "_saved_dpm", {})

        def pre_apply() -> str | None:
            self._saved_dpm = {}
            for path in paths:
                try:
                    with open(path, encoding="utf-8") as fh:
                        self._saved_dpm[path] = fh.read().strip()
                except OSError:
                    continue
            self.backup.snapshot(
                kind=GAMING_BACKUP_KIND,
                label="Nivel de energía de GPU antes del modo gaming",
                data={"dpm": self._saved_dpm},
            )
            return None

        def root_command() -> str:
            return "; ".join(f"echo 'high' > {p}" for p in paths)

        def mark_applied() -> str:
            values = {_read_file(p) for p in paths}
            if values == {"high"}:
                return f"GPU AMD forzada a «high» en {len(paths)} tarjeta(s)"
            return f"⚠ Nivel actual: {', '.join(values)}"

        def revert_command() -> str:
            if not self._saved_dpm:
                return "true"
            return "; ".join(
                f"echo '{value}' > {path}" for path, value in self._saved_dpm.items()
            )

        def mark_reverted() -> str:
            values = sorted(set(self._saved_dpm.values()))
            self._saved_dpm = {}
            return f"GPU AMD restaurada: {', '.join(values) or 'auto'}"

        action.pre_apply = pre_apply
        action.root_command = root_command
        action.mark_applied = mark_applied
        action.revert_command = revert_command
        action.mark_reverted = mark_reverted
        return action

    def _action_swappiness(self) -> GamingAction:
        def _current() -> int:
            try:
                with open("/proc/sys/vm/swappiness", encoding="utf-8") as fh:
                    return int(fh.read().strip())
            except (OSError, ValueError):
                return 60

        action = GamingAction(
            key="swappiness_low",
            title="Swappiness bajo (10)",
            description="Reduce el uso de swap durante el juego para evitar micro-tirones.",
            needs_root=True,
        )
        self._saved_swappiness = getattr(self, "_saved_swappiness", None)

        def pre_apply() -> str | None:
            self._saved_swappiness = _current()
            self.backup.snapshot(
                kind=GAMING_BACKUP_KIND,
                label=f"Swappiness antes del modo gaming: {self._saved_swappiness}",
                data={"swappiness": self._saved_swappiness},
            )
            return None

        def root_command() -> str:
            return "echo '10' > /proc/sys/vm/swappiness"

        def mark_applied() -> str:
            now = _current()
            return (f"vm.swappiness = {now}"
                    + (f" (antes: {self._saved_swappiness})" if self._saved_swappiness is not None else ""))

        def revert_command() -> str:
            if self._saved_swappiness is None:
                return "true"
            return f"echo '{self._saved_swappiness}' > /proc/sys/vm/swappiness"

        def mark_reverted() -> str:
            value = self._saved_swappiness
            self._saved_swappiness = None
            return f"vm.swappiness restaurado a {value}"

        action.pre_apply = pre_apply
        action.root_command = root_command
        action.mark_applied = mark_applied
        action.revert_command = revert_command
        action.mark_reverted = mark_reverted
        return action

    def _action_drop_caches(self) -> GamingAction:
        action = GamingAction(
            key="drop_caches",
            title="Liberar cachés del kernel",
            description="Sincroniza discos y libera la caché de páginas del kernel "
                        "antes de jugar. No requiere reversión.",
            needs_root=True,
        )

        def root_command() -> str:
            return "sync; echo 3 > /proc/sys/vm/drop_caches"

        def mark_applied() -> str:
            return "Cachés del kernel liberadas"

        action.root_command = root_command
        action.mark_applied = mark_applied
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
    # Aplicación / reversión por lotes (un solo diálogo de pkexec)
    # ------------------------------------------------------------------

    def apply(self, keys: list[str]) -> tuple[list[str], list[str]]:
        """Aplica las acciones cuyas claves se pasan. Devuelve (éxitos, errores)."""
        ok: list[str] = []
        failed: list[str] = []
        selected = [a for a in self.actions
                    if a.key in keys and a.supported and not a.applied]

        # 1) Acciones de usuario, en el proceso actual.
        for action in selected:
            if not action.needs_root and action.apply is not None:
                success, message = action.apply()
                if success:
                    action.applied = True
                    ok.append(f"{action.title}: {message}")
                else:
                    failed.append(f"{action.title}: {message}")

        # 2) Acciones root: snapshots previos + un único pkexec.
        root_actions = [a for a in selected if a.needs_root and a.root_command is not None]
        for action in root_actions:
            try:
                pre_error = action.pre_apply() if action.pre_apply else None
                if pre_error:
                    failed.append(f"{action.title}: {pre_error}")
            except Exception as exc:  # noqa: BLE001
                failed.append(f"{action.title}: respaldo previo falló: {exc}")
                root_actions.remove(action)

        if root_actions:
            commands = [(a.key, a.root_command()) for a in root_actions]
            by_key = {a.key: a for a in root_actions}
            rc, out, err = run_privileged(
                ["bash", "-c", build_batch_script(commands)], timeout=180,
            )
            parsed = _parse_batch_output(out)
            for key, cmd_rc in parsed.items():
                action = by_key[key]
                if cmd_rc == 0:
                    action.applied = True
                    ok.append(f"{action.title}: {action.mark_applied()}")
                else:
                    failed.append(f"{action.title}: comando falló (rc={cmd_rc})")
            for action in root_actions:
                if action.key not in parsed:
                    if rc == 126 or "dismissed" in (err or "").lower() \
                            or "not authorized" in (err or "").lower():
                        failed.append(f"{action.title}: autenticación cancelada")
                    else:
                        failed.append(
                            f"{action.title}: {err.strip() or f'pkexec rc={rc}'}")
        log.info("apply(claves=%s) → ok=%s | fallidas=%s", keys, ok, failed)
        return ok, failed

    def revert_all(self) -> tuple[list[str], list[str]]:
        ok: list[str] = []
        failed: list[str] = []
        root_to_revert = [a for a in self.actions
                          if a.applied and a.needs_root and a.revert_command is not None]

        # 1) Reversiones de usuario (sin root).
        for action in self.actions:
            if not action.applied or action.needs_root:
                continue
            if action.key == "clean_cache":
                action.applied = False
                ok.append(f"{action.title}: la caché vaciada no necesita revertirse")
                continue
            success, message = action.apply()
            if success:
                action.applied = False
                ok.append(f"{action.title}: {message}")
            else:
                failed.append(f"{action.title}: {message}")

        # 2) Reversiones root en un único pkexec.
        if root_to_revert:
            commands = [(a.key, a.revert_command()) for a in root_to_revert]
            by_key = {a.key: a for a in root_to_revert}
            rc, out, err = run_privileged(
                ["bash", "-c", build_batch_script(commands)], timeout=180,
            )
            parsed = _parse_batch_output(out)
            for key, cmd_rc in parsed.items():
                action = by_key[key]
                if cmd_rc == 0:
                    action.applied = False
                    ok.append(f"{action.title}: {action.mark_reverted()}")
                else:
                    failed.append(f"{action.title}: reversión falló (rc={cmd_rc})")
            for action in root_to_revert:
                if action.key not in parsed:
                    failed.append(f"{action.title}: {err.strip() or f'pkexec rc={rc}'}")

        # 3) Acciones root sin reversión (ej. drop_caches): solo limpiar estado.
        for action in self.actions:
            if action.applied and action.needs_root and action.revert_command is None:
                action.applied = False
                ok.append(f"{action.title}: no requiere reversión")
        log.info("revert_all() → ok=%s | fallidas=%s", ok, failed)
        return ok, failed

    def pending_reverts(self) -> int:
        return sum(1 for a in self.actions if a.applied)

    def gamemode_installed(self) -> bool:
        return shutil.which("gamemoded") is not None or shutil.which("gamemode") is not None

    def hardware_summary(self) -> str:
        cpu = hardware.detect_cpu()
        gpus = hardware.detect_gpus()
        gpu_text = ", ".join(g.short() for g in gpus) if gpus else "GPU no detectada"
        return f"{cpu.model} · {gpu_text}"


def _read_governor(path: str) -> str:
    try:
        with open(path, encoding="utf-8") as fh:
            return fh.read().strip()
    except OSError:
        return ""


def _read_file(path: str) -> str:
    return _read_governor(path)


def _fmt(num: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(num) < 1024 or unit == "TB":
            return f"{num:,.1f} {unit}"
        num /= 1024
    return f"{num:,.1f} TB"
