"""Módulo de memoria RAM de Cortex Gaming Engine."""

from __future__ import annotations

import shlex
from pathlib import Path

TuneCommand = tuple[str, str, str]

PROFILE_MEMORY = {
    "eco": {},
    "balanced": {"swappiness": 30},
    "extreme": {"swappiness": 10, "max_map_count": 1048576},
}


def _read_int(path: Path) -> int | None:
    try:
        return int(path.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None


def _write_command(path: Path, value: int) -> str:
    return f"echo {shlex.quote(str(value))} > {shlex.quote(str(path))}"


class MemoryModule:
    """Ajustes de memoria y acción puntual de liberación de caché."""

    def __init__(self, vm_root: Path | str | None = None):
        self.root = Path(vm_root) if vm_root is not None else Path(
            "/proc/sys/vm")

    def swappiness_path(self) -> Path:
        return self.root / "swappiness"

    def max_map_count_path(self) -> Path:
        return self.root / "max_map_count"

    def drop_caches_path(self) -> Path:
        return self.root / "drop_caches"

    def state(self) -> dict:
        return {
            "swappiness": _read_int(self.swappiness_path()),
            "max_map_count": _read_int(self.max_map_count_path()),
        }

    # ------------------------------------------------------------------

    def snapshot(self) -> dict:
        return {
            "swappiness": _read_int(self.swappiness_path()),
            "max_map_count": _read_int(self.max_map_count_path()),
        }

    def commands(self, profile: str) -> list[TuneCommand]:
        spec = PROFILE_MEMORY.get(profile)
        if not spec:
            return []
        commands: list[TuneCommand] = []
        if "swappiness" in spec:
            commands.append((
                "mem_swappiness",
                _write_command(self.swappiness_path(), spec["swappiness"]),
                f"Swappiness en {spec['swappiness']}",
            ))
        if "max_map_count" in spec:
            commands.append((
                "mem_max_map",
                _write_command(self.max_map_count_path(), spec["max_map_count"]),
                f"max_map_count en {spec['max_map_count']}",
            ))
        return commands

    def revert_commands(self, snapshot: dict) -> list[TuneCommand]:
        commands: list[TuneCommand] = []
        swappiness = snapshot.get("swappiness")
        if swappiness is not None:
            commands.append((
                "mem_swappiness",
                _write_command(self.swappiness_path(), int(swappiness)),
                f"Swappiness restaurado a {swappiness}",
            ))
        max_map = snapshot.get("max_map_count")
        if max_map is not None:
            commands.append((
                "mem_max_map",
                _write_command(self.max_map_count_path(), int(max_map)),
                f"max_map_count restaurado a {max_map}",
            ))
        return commands

    def drop_caches_commands(self) -> list[TuneCommand]:
        return [(
            "mem_drop_caches",
            f"sync; echo 3 > {shlex.quote(str(self.drop_caches_path()))}",
            "Cachés del kernel liberadas",
        )]
