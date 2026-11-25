"""Módulo de GPU de Cortex Gaming Engine (AMD, Intel y NVIDIA)."""

from __future__ import annotations

import shlex
from pathlib import Path

from linux_optimizer.core.hardware import GPUInfo, detect_gpus

TuneCommand = tuple[str, str, str]

PROFILE_GPU = {
    "eco": {"amd": "low", "intel": "low"},
    "balanced": {"amd": "auto", "intel": "max"},
    "extreme": {"amd": "high", "intel": "max"},
}


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def _write_command(path: Path, value: str) -> str:
    return f"echo {shlex.quote(value)} > {shlex.quote(str(path))}"


class GpuModule:
    """Controla el nivel de energía de AMD y el techo de frecuencia de Intel.

    NVIDIA se detecta y se muestra, pero sus relojes/energía se gestionan con
    su propio driver: Cortex no fuerza valores a ciegas.
    """

    def __init__(self, drm_root: Path | str | None = None,
                 gpus: list[GPUInfo] | None = None):
        self.drm_root = Path(drm_root) if drm_root is not None else Path(
            "/sys/class/drm")
        self.gpus = gpus if gpus is not None else detect_gpus()

    # ------------------------------------------------------------------
    # Detección
    # ------------------------------------------------------------------

    def amd_paths(self) -> list[Path]:
        return sorted(self.drm_root.glob(
            "card*/device/power_dpm_force_performance_level"))

    def intel_pairs(self) -> list[tuple[Path, Path]]:
        pairs: list[tuple[Path, Path]] = []
        candidates = (list(self.drm_root.glob("card*/device/gt_max_freq_mhz"))
                      + list(self.drm_root.glob("card*/gt_max_freq_mhz")))
        for max_path in sorted(candidates):
            rp0 = max_path.with_name("gt_RP0_freq_mhz")
            if rp0.exists():
                pairs.append((max_path, rp0))
        return pairs

    def vendors(self) -> list[str]:
        return sorted({gpu.vendor for gpu in self.gpus if gpu.vendor != "unknown"})

    def state(self) -> dict:
        return {
            "amd": {str(p): _read(p) for p in self.amd_paths()},
            "intel": {str(p): _read(p) for p, _rp0 in self.intel_pairs()},
            "vendors": self.vendors(),
            "gpus": self.gpus,
        }

    def notes(self) -> list[str]:
        notes = []
        if "nvidia" in self.vendors():
            notes.append(
                "NVIDIA: los relojes y el consumo se controlan con su driver "
                "(nvidia-settings); Cortex no fuerza valores.")
        intel = self.intel_pairs()
        if intel and not any(
                p.with_name("gt_RP1_freq_mhz").exists() for p, _ in intel):
            notes.append("GPU Intel: el perfil ECO no puede bajar el techo de "
                         "frecuencia en este driver; se deja como está.")
        return notes

    # ------------------------------------------------------------------
    # Instantánea y comandos
    # ------------------------------------------------------------------

    def snapshot(self) -> dict:
        return {
            "amd": {str(p): _read(p) for p in self.amd_paths()},
            "intel": {str(p): _read(p) for p, _rp0 in self.intel_pairs()},
        }

    def commands(self, profile: str) -> list[TuneCommand]:
        if profile not in PROFILE_GPU:
            return []
        spec = PROFILE_GPU[profile]
        commands: list[TuneCommand] = []

        amd_paths = self.amd_paths()
        if amd_paths:
            level = spec["amd"]
            shell = "; ".join(_write_command(p, level) for p in amd_paths)
            commands.append((
                "gpu_amd", shell,
                f"GPU AMD en «{ 'máximo' if level == 'high' else 'ahorro' if level == 'low' else 'automático' }»"
                f" ({len(amd_paths)} tarjeta(s))",
            ))

        intel_pairs = self.intel_pairs()
        if intel_pairs:
            commands_intel: list[str] = []
            for max_path, rp0_path in intel_pairs:
                if spec["intel"] == "low":
                    rp1 = max_path.with_name("gt_RP1_freq_mhz")
                    target = _read(rp1) if rp1.exists() else ""
                else:
                    target = _read(rp0_path)
                if target:
                    commands_intel.append(_write_command(max_path, target))
            if commands_intel:
                label = ("frecuencia máxima" if spec["intel"] == "max"
                         else "frecuencia reducida")
                commands.append((
                    "gpu_intel", "; ".join(commands_intel),
                    f"GPU Intel en {label} ({len(intel_pairs)} tarjeta(s))",
                ))
        return commands

    def revert_commands(self, snapshot: dict) -> list[TuneCommand]:
        commands: list[TuneCommand] = []
        for key, label in (("amd", "Nivel de energía de GPU AMD restaurado"),
                           ("intel", "Frecuencia de GPU Intel restaurada")):
            saved = snapshot.get(key) or {}
            shell = "; ".join(
                _write_command(Path(path), value)
                for path, value in saved.items() if value)
            if shell:
                commands.append((f"gpu_{key}", shell, label))
        return commands
