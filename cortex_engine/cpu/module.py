"""Módulo de CPU de Cortex Gaming Engine."""

from __future__ import annotations

import glob
import shlex
from pathlib import Path

from cortex_engine.config import PROFILE_KEYS

# TuneCommand = (clave_para_el_lote, comando_shell, descripción legible)
TuneCommand = tuple[str, str, str]

PROFILE_CPU: dict[str, dict] = {
    "eco": {"governor": "powersave", "epp": "power", "boost": False},
    "balanced": {
        "governor": "schedutil",
        "fallback_governor": "ondemand",
        "epp": "balance_performance",
        "epp_fallback": "balance_power",
        "boost": True,
    },
    "extreme": {"governor": "performance", "epp": "performance", "boost": True},
}


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def _write_command(path: Path, value: str) -> str:
    return f"echo {shlex.quote(value)} > {shlex.quote(str(path))}"


class CpuModule:
    """Detecta los controles de CPU disponibles y genera comandos por perfil."""

    def __init__(self, cpu_root: Path | str | None = None):
        self.root = Path(cpu_root) if cpu_root is not None else Path(
            "/sys/devices/system/cpu")

    # ------------------------------------------------------------------
    # Detección
    # ------------------------------------------------------------------

    def governor_paths(self) -> list[Path]:
        return sorted(self.root.glob("cpu*/cpufreq/scaling_governor"))

    def epp_paths(self) -> list[Path]:
        return sorted(
            self.root.glob("cpu*/cpufreq/energy_performance_preference"))

    def boost_path(self) -> Path | None:
        intel_no_turbo = self.root / "intel_pstate/no_turbo"
        cpufreq_boost = self.root / "cpufreq/boost"
        if intel_no_turbo.exists():
            return intel_no_turbo
        if cpufreq_boost.exists():
            return cpufreq_boost
        return None

    def available_governors(self) -> list[str]:
        paths = sorted(glob.glob(str(
            self.root / "cpu0/cpufreq/scaling_available_governors")))
        if not paths:
            return []
        return _read(Path(paths[0])).split()

    def available_epp(self) -> list[str]:
        path = self.root / "cpu0/cpufreq/energy_performance_available_preferences"
        return _read(path).split()

    def state(self) -> dict:
        governors = self.governor_paths()
        epps = self.epp_paths()
        boost = self.boost_path()
        boost_value = _read(boost) if boost else ""
        return {
            "governor": _read(governors[0]) if governors else "",
            "epp": _read(epps[0]) if epps else "",
            "boost": ("sí" if boost_value in ("0", "1") and
                      ((boost.name == "no_turbo" and boost_value == "0") or
                       (boost.name == "boost" and boost_value == "1"))
                      else "no" if boost_value else ""),
            "available_governors": self.available_governors(),
            "available_epp": self.available_epp(),
            "cpus": len(governors),
        }

    # ------------------------------------------------------------------
    # Instantánea y comandos
    # ------------------------------------------------------------------

    def snapshot(self) -> dict:
        boost = self.boost_path()
        return {
            "governor": {str(p): _read(p) for p in self.governor_paths()},
            "epp": {str(p): _read(p) for p in self.epp_paths()},
            "boost": ({"path": str(boost), "value": _read(boost)}
                      if boost else {}),
        }

    def commands(self, profile: str) -> list[TuneCommand]:
        if profile not in PROFILE_KEYS:
            return []
        spec = PROFILE_CPU[profile]
        commands: list[TuneCommand] = []

        governors = self.governor_paths()
        if governors:
            wanted = spec.get("governor", "")
            available = self.available_governors()
            if wanted and available and wanted not in available:
                wanted = spec.get("fallback_governor", "")
            if wanted and (not available or wanted in available):
                shell = "; ".join(_write_command(p, wanted) for p in governors)
                commands.append((
                    "cpu_governor", shell,
                    f"Governor «{wanted}» en {len(governors)} CPU",
                ))

        epps = self.epp_paths()
        if epps:
            wanted = spec.get("epp", "")
            available = self.available_epp()
            if wanted and available and wanted not in available:
                wanted = spec.get("epp_fallback", "")
            if wanted and (not available or wanted in available):
                shell = "; ".join(_write_command(p, wanted) for p in epps)
                commands.append((
                    "cpu_epp", shell,
                    f"Preferencia de energía «{wanted}» en {len(epps)} CPU",
                ))

        boost = self.boost_path()
        desired = spec.get("boost")
        if boost is not None and desired is not None:
            if boost.name == "no_turbo":
                value = "0" if desired else "1"
                label = "Turbo activado" if desired else "Turbo desactivado"
            else:
                value = "1" if desired else "0"
                label = "Boost activado" if desired else "Boost desactivado"
            commands.append(("cpu_boost", _write_command(boost, value), label))
        return commands

    def revert_commands(self, snapshot: dict) -> list[TuneCommand]:
        commands: list[TuneCommand] = []
        saved_governors = snapshot.get("governor") or {}
        if saved_governors:
            shell = "; ".join(
                _write_command(Path(path), value)
                for path, value in saved_governors.items() if value)
            if shell:
                commands.append(("cpu_governor", shell,
                                 "Governor de CPU restaurado"))
        saved_epp = snapshot.get("epp") or {}
        if saved_epp:
            shell = "; ".join(
                _write_command(Path(path), value)
                for path, value in saved_epp.items() if value)
            if shell:
                commands.append(("cpu_epp", shell,
                                 "Preferencia de energía restaurada"))
        saved_boost = snapshot.get("boost") or {}
        if saved_boost.get("path") and saved_boost.get("value"):
            commands.append((
                "cpu_boost",
                _write_command(Path(saved_boost["path"]), saved_boost["value"]),
                "Turbo/boost de CPU restaurado",
            ))
        return commands
