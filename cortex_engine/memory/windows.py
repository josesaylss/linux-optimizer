"""Memoria en Windows: Cortex no modifica swappiness ni cachés del kernel."""

from __future__ import annotations


class WindowsMemoryModule:
    """Interfaz compatible con ``MemoryModule`` sin controles inseguros."""

    def state(self) -> dict:
        return {"swappiness": None, "max_map_count": None}

    def snapshot(self) -> dict:
        return {}

    def commands(self, profile: str) -> list[tuple[str, str, str]]:
        return []

    def revert_commands(self, snapshot: dict) -> list[tuple[str, str, str]]:
        return []

    def drop_caches_commands(self) -> list[tuple[str, str, str]]:
        return []
