"""Detección automática de hardware (CPU, RAM, GPU, discos, temperatura)."""

from __future__ import annotations

import glob
import os
import re
import subprocess
from dataclasses import dataclass, field

import psutil

from linux_optimizer.core import platform_info


@dataclass(frozen=True)
class GPUInfo:
    name: str
    vendor: str  # nvidia | amd | intel | unknown
    pci_slot: str = ""
    driver: str = ""
    sysfs_path: str = ""

    def short(self) -> str:
        return self.name or "GPU desconocida"


@dataclass(frozen=True)
class DiskInfo:
    device: str
    mount: str
    fstype: str
    total: int
    used: int
    free: int


@dataclass(frozen=True)
class CPUInfo:
    model: str
    cores_physical: int
    cores_logical: int
    max_freq_mhz: float = 0.0


@dataclass
class HardwareSnapshot:
    cpu: CPUInfo
    mem_total: int
    gpus: list[GPUInfo] = field(default_factory=list)
    distro_extra: dict[str, str] = field(default_factory=dict)


# ----------------------------------------------------------------------------
# CPU
# ----------------------------------------------------------------------------

def detect_cpu() -> CPUInfo:
    model = ""
    try:
        with open("/proc/cpuinfo", encoding="utf-8") as fh:
            for line in fh:
                if line.startswith("model name"):
                    model = line.split(":", 1)[1].strip()
                    break
    except OSError:
        pass
    freq = psutil.cpu_freq()
    return CPUInfo(
        model=model or platform.processor() or "CPU",
        cores_physical=psutil.cpu_count(logical=False) or psutil.cpu_count() or 0,
        cores_logical=psutil.cpu_count(logical=True) or 0,
        max_freq_mhz=float(freq.max) if freq and freq.max else 0.0,
    )


# ----------------------------------------------------------------------------
# GPU
# ----------------------------------------------------------------------------

_PCI_VENDOR_IDS = {
    "10de": "nvidia",
    "8086": "intel",
    "1002": "amd",
    "1022": "amd",
}


def _parse_pci_vendor(value: str) -> str:
    match = re.search(r"\[([0-9a-fA-F]{4})\]", value)
    if match:
        return _PCI_VENDOR_IDS.get(match.group(1).lower(), "unknown")
    return "unknown"


def _gpu_driver(slot: str) -> str:
    """Nombre del controlador del kernel para el slot PCI indicado."""
    path = f"/sys/bus/pci/devices/{slot}/driver"
    try:
        return os.path.basename(os.path.realpath(path))
    except OSError:
        return ""


def _gpus_from_lspci() -> list[GPUInfo]:
    try:
        proc = subprocess.run(
            ["lspci", "-mm", "-nn", "-D"],
            capture_output=True, text=True, timeout=10, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    gpus: list[GPUInfo] = []
    for line in proc.stdout.splitlines():
        low = line.lower()
        if "vga" not in low and "3d controller" not in low and "display controller" not in low:
            continue
        parts = line.split('"')
        if len(parts) < 4:
            continue
        slot = parts[0].strip()
        vendor = _parse_pci_vendor(parts[3])
        # Nombre limpio: sin las etiquetas de IDs de lspci -nn ("[15d8]").
        name = parts[5] if len(parts) > 5 else ""
        while True:
            stripped = re.sub(r"\s*\[[0-9a-fA-F:]+\]\s*$", "", name)
            if stripped == name:
                break
            name = stripped
        name = name.strip() or f"GPU ({vendor})"
        gpus.append(GPUInfo(
            name=name, vendor=vendor, pci_slot=slot, driver=_gpu_driver(slot),
            sysfs_path=f"/sys/bus/pci/devices/{slot}",
        ))
    return gpus


def _gpus_from_sysfs() -> list[GPUInfo]:
    """Respaldo si lspci no está disponible (pciutils no instalado)."""
    gpus: list[GPUInfo] = []
    try:
        entries = sorted(os.listdir("/sys/class/drm"))
    except OSError:
        return gpus
    seen: set[str] = set()
    for entry in entries:
        if not entry.startswith("card"):
            continue
        if not os.path.isdir(os.path.join("/sys/class/drm", entry, "device")):
            continue
        base = f"/sys/class/drm/{entry}/device"
        try:
            with open(os.path.join(base, "vendor"), encoding="utf-8") as fh:
                vendor_id = fh.read().strip().lower().replace("0x", "")
        except OSError:
            continue
        vendor = _PCI_VENDOR_IDS.get(vendor_id, "unknown")
        if vendor in seen:
            continue
        seen.add(vendor)
        slot = os.path.basename(os.path.realpath(base))
        gpus.append(GPUInfo(
            name=f"GPU {vendor.capitalize()}",
            vendor=vendor,
            pci_slot=slot,
            driver=_gpu_driver(slot),
            sysfs_path=f"/sys/bus/pci/devices/{slot}",
        ))
    return gpus


def _gpus_from_windows() -> list[GPUInfo]:
    """GPUs en Windows vía PowerShell CIM (sin dependencias externas)."""
    commands = [
        ["powershell", "-NoProfile", "-NonInteractive", "-Command",
         "Get-CimInstance Win32_VideoController | "
         "ForEach-Object { $_.Name }"],
        ["wmic", "path", "win32_VideoController", "get", "name"],
    ]
    names: list[str] = []
    for command in commands:
        try:
            proc = subprocess.run(command, capture_output=True, text=True,
                                  timeout=15, check=False)
        except (OSError, subprocess.TimeoutExpired):
            continue
        if proc.returncode != 0:
            continue
        for line in proc.stdout.splitlines():
            value = line.strip()
            if not value or value.lower() == "name":
                continue
            names.append(value)
        if names:
            break

    gpus: list[GPUInfo] = []
    seen: set[str] = set()
    for name in names:
        low = name.lower()
        if "nvidia" in low:
            vendor = "nvidia"
        elif "amd" in low or "radeon" in low:
            vendor = "amd"
        elif "intel" in low:
            vendor = "intel"
        else:
            vendor = "unknown"
        key = (name, vendor)
        if key in seen:
            continue
        seen.add(key)
        gpus.append(GPUInfo(name=name, vendor=vendor, driver="wddm"))
    return gpus


def detect_gpus() -> list[GPUInfo]:
    if platform_info.IS_WINDOWS:
        return _gpus_from_windows()
    gpus = _gpus_from_lspci() or _gpus_from_sysfs()
    if not gpus:
        return []
    # Información extra de NVIDIA si hay controlador propietario.
    try:
        proc = subprocess.run(
            ["nvidia-smi", "--query-gpu=name",
             "--format=csv,noheader"],
            capture_output=True, text=True, timeout=5, check=False,
        )
        if proc.returncode == 0 and proc.stdout.strip():
            names = [n.strip() for n in proc.stdout.splitlines() if n.strip()]
            idx = 0
            rebuilt = []
            for gpu in gpus:
                if gpu.vendor == "nvidia" and idx < len(names):
                    gpu = GPUInfo(name=names[idx], vendor=gpu.vendor,
                                  pci_slot=gpu.pci_slot, driver=gpu.driver,
                                  sysfs_path=gpu.sysfs_path)
                    idx += 1
                rebuilt.append(gpu)
            gpus = rebuilt
    except (OSError, subprocess.TimeoutExpired):
        pass
    return gpus


# ----------------------------------------------------------------------------
# Discos
# ----------------------------------------------------------------------------

def detect_disks() -> list[DiskInfo]:
    """Discos/particiones montadas con espacio real en uso."""
    disks: list[DiskInfo] = []
    seen: set[str] = set()
    for part in psutil.disk_partitions(all=False):
        if part.mountpoint in seen or part.fstype in ("squashfs", "tmpfs", "efivarfs"):
            continue
        seen.add(part.mountpoint)
        try:
            usage = psutil.disk_usage(part.mountpoint)
        except (OSError, PermissionError):
            continue
        disks.append(DiskInfo(
            device=part.device,
            mount=part.mountpoint,
            fstype=part.fstype,
            total=usage.total,
            used=usage.used,
            free=usage.free,
        ))
    return disks


# ----------------------------------------------------------------------------
# Temperatura y batería
# ----------------------------------------------------------------------------

def _read_int_sysfs(path: str) -> float | None:
    try:
        with open(path, encoding="utf-8") as fh:
            return float(fh.read().strip())
    except (OSError, ValueError):
        return None


def sysfs_gpu_stats(gpu: GPUInfo) -> dict | None:
    """Estadísticas en vivo desde sysfs (amdgpu: gpu_busy_percent, VRAM, hwmon)."""
    if platform_info.IS_WINDOWS or not gpu.sysfs_path:
        return None
    base = gpu.sysfs_path
    if not base or not os.path.isdir(base):
        return None
    busy = _read_int_sysfs(os.path.join(base, "gpu_busy_percent"))
    vram_used = _read_int_sysfs(os.path.join(base, "mem_info_vram_used"))
    vram_total = _read_int_sysfs(os.path.join(base, "mem_info_vram_total"))
    # hwmon del dispositivo (amdgpu expone la temperatura como temp1_input).
    temp = None
    for hwmon in glob.glob(os.path.join(base, "hwmon", "hwmon*")):
        try:
            with open(os.path.join(hwmon, "name"), encoding="utf-8") as fh:
                chip = fh.read().lower()
        except OSError:
            continue
        if "amdgpu" in chip or "radeon" in chip:
            temp = _read_int_sysfs(os.path.join(hwmon, "temp1_input"))
            if temp is not None:
                temp /= 1000.0
            break
    if busy is None and temp is None:
        return None
    return {
        "name": gpu.short(),
        "util": busy if busy is not None else 0.0,
        "mem_used_mb": (vram_used or 0) / 1e6,
        "mem_total_mb": (vram_total or 0) / 1e6,
        "temp": temp if temp is not None else 0.0,
    }

def detect_temperatures() -> list[tuple[str, float]]:
    """Lista de (etiqueta, °C) de los sensores disponibles."""
    temps: list[tuple[str, float]] = []
    try:
        sensors = psutil.sensors_temperatures()
    except (AttributeError, OSError):
        sensors = {}
    for chip, entries in (sensors or {}).items():
        for entry in entries:
            label = entry.label or chip
            if entry.current is not None:
                temps.append((f"{chip}/{label}", float(entry.current)))
    return temps


def detect_battery() -> dict | None:
    try:
        battery = psutil.sensors_battery()
    except (AttributeError, OSError):
        return None
    if battery is None:
        return None
    plugged = battery.power_plugged
    return {
        "percent": round(battery.percent, 1),
        "secs_left": battery.secsleft,
        "plugged": plugged,
    }


def hardware_snapshot() -> HardwareSnapshot:
    return HardwareSnapshot(
        cpu=detect_cpu(),
        mem_total=psutil.virtual_memory().total,
        gpus=detect_gpus(),
    )
