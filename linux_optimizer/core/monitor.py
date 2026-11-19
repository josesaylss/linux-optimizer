"""Monitor de recursos del sistema basado en psutil + QTimer."""

from __future__ import annotations

import subprocess
import time

import psutil
from PySide6.QtCore import QObject, QTimer, Signal

from linux_optimizer.core.hardware import (
    CPUInfo,
    GPUInfo,
    detect_cpu,
    detect_disks,
    detect_gpus,
    detect_temperatures,
    sysfs_gpu_stats,
)


def _nvidia_stats() -> dict[str, dict]:
    """Estadísticas de GPUs NVIDIA indexadas por nombre (vía nvidia-smi)."""
    try:
        proc = subprocess.run(
            ["nvidia-smi",
             "--query-gpu=name,utilization.gpu,memory.used,memory.total,temperature.gpu",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return {}
    if proc.returncode != 0:
        return {}
    stats: dict[str, dict] = {}
    for line in proc.stdout.splitlines():
        fields = [f.strip() for f in line.split(",")]
        if len(fields) != 5:
            continue
        try:
            stats[fields[0]] = {
                "name": fields[0],
                "util": float(fields[1]),
                "mem_used_mb": float(fields[2]),
                "mem_total_mb": float(fields[3]),
                "temp": float(fields[4]),
            }
        except ValueError:
            continue
    return stats


def gpu_live_stats(gpus: list[GPUInfo]) -> list[dict]:
    """Estadísticas en vivo por GPU: nvidia-smi para NVIDIA, sysfs para el resto."""
    nvidia = _nvidia_stats()
    stats: list[dict] = []
    for gpu in gpus:
        if gpu.vendor == "nvidia" and nvidia:
            stats.append(nvidia[gpu.name] if gpu.name in nvidia else next(iter(nvidia.values())))
            continue
        sysfs = sysfs_gpu_stats(gpu)
        if sysfs:
            stats.append(sysfs)
    return stats


def thread_count() -> int:
    """Número total de hilos del sistema (cuarto campo de /proc/loadavg)."""
    try:
        with open("/proc/loadavg", encoding="ascii") as fh:
            field = fh.read().split()[3]  # "en_ejecución/total"
        return int(field.split("/")[1])
    except (OSError, ValueError, IndexError):
        return 0


class SystemMonitor(QObject):
    """Muestrea el sistema cada N ms y emite `stats_updated` con un dict."""

    stats_updated = Signal(dict)

    DEFAULT_INTERVAL_MS = 2000

    def __init__(self, interval_ms: int = DEFAULT_INTERVAL_MS, parent: QObject | None = None):
        super().__init__(parent)
        self.cpu_info: CPUInfo = detect_cpu()
        self.gpus: list[GPUInfo] = detect_gpus()
        self._timer = QTimer(self)
        self._timer.setInterval(interval_ms)
        self._timer.timeout.connect(self.collect_once)
        self._last_disk_io = psutil.disk_io_counters()
        self._last_net_io = psutil.net_io_counters()
        self._last_time = time.monotonic()
        # Primera lectura para inicializar los contadores no bloqueantes.
        psutil.cpu_percent(interval=None)
        psutil.cpu_percent(percpu=True, interval=None)

    # ------------------------------------------------------------------
    # Ciclo de vida
    # ------------------------------------------------------------------

    def start(self) -> None:
        if not self._timer.isActive():
            self.collect_once()  # poblar la UI de inmediato
            self._timer.start()

    def stop(self) -> None:
        self._timer.stop()

    # ------------------------------------------------------------------
    # Recolección
    # ------------------------------------------------------------------

    def collect_once(self) -> dict:
        now = time.monotonic()
        dt = max(now - self._last_time, 1e-6)

        cpu_percent = psutil.cpu_percent(interval=None)
        cpu_percpu = psutil.cpu_percent(percpu=True, interval=None)
        freq = psutil.cpu_freq()

        vm = psutil.virtual_memory()
        swap = psutil.swap_memory()

        disks = detect_disks()

        disk_io = psutil.disk_io_counters()
        disk_read_rate = disk_write_rate = 0
        if disk_io and self._last_disk_io:
            disk_read_rate = max(0, disk_io.read_bytes - self._last_disk_io.read_bytes) / dt
            disk_write_rate = max(0, disk_io.write_bytes - self._last_disk_io.write_bytes) / dt
        self._last_disk_io = disk_io

        net_io = psutil.net_io_counters()
        net_rx_rate = net_tx_rate = 0
        if net_io and self._last_net_io:
            net_rx_rate = max(0, net_io.bytes_recv - self._last_net_io.bytes_recv) / dt
            net_tx_rate = max(0, net_io.bytes_sent - self._last_net_io.bytes_sent) / dt
        self._last_net_io = net_io
        self._last_time = now

        temps = detect_temperatures()
        gpu_stats = gpu_live_stats(self.gpus) if self.gpus else []

        stats = {
            "cpu": {
                "percent": cpu_percent,
                "per_core": cpu_percpu,
                "freq_mhz": float(freq.current) if freq and freq.current else 0.0,
                "model": self.cpu_info.model,
                "cores_physical": self.cpu_info.cores_physical,
                "cores_logical": self.cpu_info.cores_logical,
            },
            "mem": {
                "total": vm.total,
                "used": vm.used,
                "available": vm.available,
                "percent": vm.percent,
            },
            "swap": {
                "total": swap.total,
                "used": swap.used,
                "percent": swap.percent,
            },
            "disks": [
                {
                    "device": d.device,
                    "mount": d.mount,
                    "fstype": d.fstype,
                    "total": d.total,
                    "used": d.used,
                    "free": d.free,
                    "percent": round(d.used * 100 / d.total, 1) if d.total else 0.0,
                }
                for d in disks
            ],
            "disk_io": {
                "read_bps": disk_read_rate,
                "write_bps": disk_write_rate,
            },
            "net_io": {
                "rx_bps": net_rx_rate,
                "tx_bps": net_tx_rate,
            },
            "temps": temps,
            "gpus": self.gpus and gpu_stats or [],
            "gpu_names": [g.short() for g in self.gpus],
            "threads": thread_count(),
            "uptime_secs": _uptime(),
        }
        self.stats_updated.emit(stats)
        return stats


def _uptime() -> float:
    return max(time.time() - psutil.boot_time(), 0.0)
