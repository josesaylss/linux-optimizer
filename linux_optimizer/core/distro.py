"""Detección de distribución y escritorio.

Arquitectura multi-distro: la app clasifica las distribuciones en
"familias" (fedora, debian, arch) que determinan gestor de paquetes,
comandos de limpieza y perfil de energía disponibles.
"""

from __future__ import annotations

import os
import platform
from dataclasses import dataclass

FAMILIES = ("fedora", "debian", "arch", "unknown")


@dataclass(frozen=True)
class DistroInfo:
    """Información de la distribución detectada."""

    name: str
    version: str
    family: str  # fedora | debian | arch | unknown
    package_manager: str  # dnf | apt | pacman | unknown
    desktop: str  # KDE | GNOME | XFCE | ... ("" si no hay sesión gráfica)
    is_supported: bool

    @property
    def pretty(self) -> str:
        desktop = self.desktop or "sin escritorio"
        return f"{self.name} {self.version} · {desktop}".rstrip()


# Mapa id de /etc/os-release -> familia soportada.
_FAMILY_BY_ID = {
    "fedora": "fedora",
    "rhel": "fedora",
    "centos": "fedora",
    "centos-stream": "fedora",
    "rocky": "fedora",
    "almalinux": "fedora",
    "nobara": "fedora",
    "silverblue": "fedora",
    "ultramarine": "fedora",
    "ubuntu": "debian",
    "debian": "debian",
    "linuxmint": "debian",
    "pop": "debian",
    "elementary": "debian",
    "kali": "debian",
    "zorin": "debian",
    "trisquel": "debian",
    "arch": "arch",
    "manjaro": "arch",
    "endeavouros": "arch",
    "garuda": "arch",
    "cachyos": "arch",
    "artix": "arch",
}

_PACKAGE_MANAGER_BY_FAMILY = {
    "fedora": "dnf",
    "debian": "apt",
    "arch": "pacman",
}


def read_os_release(path: str = "/etc/os-release") -> dict[str, str]:
    """Lee /etc/os-release (o una ruta alternativa para pruebas)."""
    data: dict[str, str] = {}
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                data[key.strip()] = value.strip().strip('"')
    except OSError:
        pass
    return data


def detect_desktop() -> str:
    """Detecta el entorno de escritorio de la sesión actual."""
    for var in ("XDG_CURRENT_DESKTOP", "DESKTOP_SESSION"):
        value = os.environ.get(var)
        if not value:
            continue
        value = value.split(":")[0].strip().lower()
        if not value:
            continue
        if "kde" in value or "plasma" in value:
            return "KDE"
        if "gnome" in value:
            return "GNOME"
        if "xfce" in value:
            return "XFCE"
        if "cinnamon" in value:
            return "Cinnamon"
        if "mate" in value:
            return "MATE"
        if "lxqt" in value:
            return "LXQt"
        if "budgie" in value:
            return "Budgie"
        return value.capitalize()
    if os.environ.get("KDE_FULL_SESSION"):
        return "KDE"
    return ""


def classify(distro_id: str) -> str:
    """Clasifica un id de distribución en una familia."""
    distro_id = (distro_id or "").lower()
    if distro_id in _FAMILY_BY_ID:
        return _FAMILY_BY_ID[distro_id]
    # IDs compuestos como "ubuntu-core" o "opensuse" no soportados aún.
    return "unknown"


def detect_distro(os_release_path: str = "/etc/os-release") -> DistroInfo:
    data = read_os_release(os_release_path)
    distro_id = data.get("ID", "") or platform.system().lower()
    name = data.get("PRETTY_NAME") or data.get("NAME") or distro_id.capitalize()
    family = classify(distro_id)
    return DistroInfo(
        name=name,
        version=data.get("VERSION_ID", ""),
        family=family,
        package_manager=_PACKAGE_MANAGER_BY_FAMILY.get(family, "unknown"),
        desktop=detect_desktop(),
        is_supported=family != "unknown",
    )
