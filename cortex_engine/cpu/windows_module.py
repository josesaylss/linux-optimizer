"""Vista de CPU para Windows (plan de energía en lugar de governor)."""

from __future__ import annotations

import psutil

from cortex_engine.cpu.windows import active_plan, plan_commands


class WindowsCpuModule:
    """Interfaz compatible con ``CpuModule`` para las páginas de Cortex."""

    def state(self) -> dict:
        plan = active_plan()
        return {
            "governor": plan.get("name") or "no disponible",
            "epp": "",
            "boost": "",
            "available_governors": [],
            "available_epp": [],
            "cpus": psutil.cpu_count(logical=True) or 0,
            "plan_guid": plan.get("guid", ""),
            "error": plan.get("error", ""),
        }

    def snapshot(self) -> dict:
        plan = active_plan()
        return {"power_plan": plan}

    def commands(self, profile: str) -> list[tuple[str, str, str]]:
        return plan_commands(profile)

    def revert_commands(self, snapshot: dict) -> list[tuple[str, str, str]]:
        return []
