"""Pruebas de detección de distribución."""

import os

from linux_optimizer.core import distro


OS_RELEASE_TEMPLATE = """ID={id}
NAME="Test OS"
VERSION_ID=42
PRETTY_NAME="Test OS 42"
"""


def _write(tmp_path, distro_id: str) -> str:
    path = tmp_path / "os-release"
    path.write_text(OS_RELEASE_TEMPLATE.format(id=distro_id), encoding="utf-8")
    return str(path)


def test_fedora_family(tmp_path):
    info = distro.detect_distro(_write(tmp_path, "fedora"))
    assert info.family == "fedora"
    assert info.package_manager == "dnf"
    assert info.is_supported


def test_ubuntu_family(tmp_path):
    info = distro.detect_distro(_write(tmp_path, "ubuntu"))
    assert info.family == "debian"
    assert info.package_manager == "apt"


def test_arch_family(tmp_path):
    info = distro.detect_distro(_write(tmp_path, "arch"))
    assert info.family == "arch"
    assert info.package_manager == "pacman"


def test_unknown_family(tmp_path):
    info = distro.detect_distro(_write(tmp_path, "opensuse"))
    assert info.family == "unknown"
    assert not info.is_supported
    assert info.package_manager == "unknown"


def test_real_os_release_if_present():
    """En una máquina Linux real siempre debe detectar algo."""
    if not os.path.exists("/etc/os-release"):
        return
    info = distro.detect_distro()
    assert info.name
    assert info.family in distro.FAMILIES
