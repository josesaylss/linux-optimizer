"""Sistema de monitorización propio de Cortex Gaming Engine.

Usa psutil y los sensores sysfs del sistema. Es independiente del monitor de
Linux Optimizer (aunque reutiliza los detectores de hardware para no duplicar
la lectura de GPU/temperaturas).
"""

from __future__ import annotations

import time

import psutil
from PySide6.QtCore import QObject, QTimer, Signal

from linux_optimizer.core.hardware import (
    CPUInfo,
    GPUInfo,
    detect_cpu,
    detect_gpus,
    detect_temperatures,
)
from linux_optimizer.core.monitor import gpu_live_stats, thread_count


def read_swappiness() -> int | None:
    try:
        with open("/proc/sys/vm/swappiness", encoding="ascii") as fh:
            return int(fh.read().strip())
    except (OSError, ValueError):
        return None


def _cpu_temperature() -> float | None:
    temps = detect_temperatures()
    for label, value in temps:
        low = label.lower()
        if any(token in low for token in ("tctl", "cpu", "package", "core")):
            return value
    return temps[0][1] if temps else None


class CortexMonitor(QObject):
    """Muestrea CPU, GPU, RAM y temperatura y emite ``stats_updated``."""

    stats_updated = Signal(dict)
    DEFAULT_INTERVAL_MS = 1500

    def __init__(self, interval_ms: int = DEFAULT_INTERVAL_MS,
                 parent: QObject | None = None):
        super().__init__(parent)
        self.cpu_info: CPUInfo = detect_cpu()
        self.gpus: list[GPUInfo] = detect_gpus()
        self._started_at = time.monotonic()
        self._timer = QTimer(self)
        self._timer.setInterval(max(500, int(interval_ms)))
        self._timer.timeout.connect(self.collect_once)
        # Inicializa los contadores no bloqueantes de psutil.
        psutil.cpu_percent(interval=None)
        psutil.cpu_percent(percpu=True, interval=None)

    # ------------------------------------------------------------------
    # Ciclo de vida
    # ------------------------------------------------------------------

    def start(self) -> None:
        if not self._timer.isActive():
            self.collect_once()
            self._timer.start()

    def stop(self) -> None:
        self._timer.stop()

    def set_interval(self, interval_ms: int) -> None:
        self._timer.setInterval(max(500, min(10000, int(interval_ms))))

    def is_running(self) -> bool:
        return self._timer.isActive()

    # ------------------------------------------------------------------
    # Recolección
    # ------------------------------------------------------------------

    def collect_once(self) -> dict:
        stats = self.collect()
        self.stats_updated.emit(stats)
        return stats

    def collect(self) -> dict:
        vm = psutil.virtual_memory()
        swap = psutil.swap_memory()
        try:
            load = list(psutil.getloadavg())
        except (AttributeError, OSError):
            load = [0.0, 0.0, 0.0]
        freq = psutil.cpu_freq()
        try:
            processes = len(psutil.pids())
        except OSError:
            processes = 0

        return {
            "cpu": {
                "percent": psutil.cpu_percent(interval=None),
                "per_core": psutil.cpu_percent(percpu=True, interval=None),
                "freq_mhz": float(freq.current) if freq else 0.0,
                "max_freq_mhz": float(freq.max) if freq and freq.max else 0.0,
                "cores": self.cpu_info.cores_physical,
                "threads": thread_count(),
                "load": load,
                "temp": _cpu_temperature(),
            },
            "ram": {
                "percent": vm.percent,
                "used_gb": vm.used / 1e9,
                "total_gb": vm.total / 1e9,
                "swap_percent": swap.percent,
                "swap_used_gb": swap.used / 1e9,
                "swap_total_gb": swap.total / 1e9,
                "swappiness": read_swappiness(),
            },
            "gpus": gpu_live_stats(self.gpus),
            "processes": processes,
            "uptime_secs": time.monotonic() - self._started_at,
        }
