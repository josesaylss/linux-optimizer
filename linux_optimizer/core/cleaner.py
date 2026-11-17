"""Limpieza segura de archivos temporales y cachés.

Principios de seguridad:
  - Solo se borra contenido de rutas bien definidas y regenerables.
  - Las rutas del sistema requieren pkexec y confirmación previa del usuario.
  - Nunca se ejecuta borrado automático: la UI pide confirmación siempre.
  - Nunca se tocan documentos, configuraciones del usuario ni datos de apps.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ScanResult:
    size: int = 0
    files: int = 0
    note: str = ""
    error: str = ""

    @property
    def ok(self) -> bool:
        return not self.error


@dataclass
class CleanResult:
    freed: int = 0
    removed: int = 0
    error: str = ""


@dataclass
class CleanTarget:
    key: str
    title: str
    description: str
    needs_root: bool
    # family limita el objetivo a una familia de distros ("fedora", ...)
    family: str | None = None
    scan: object = None      # Callable[[], ScanResult]
    clean: object = None     # Callable[[], CleanResult]

    def available(self, distro_family: str) -> bool:
        return self.family is None or self.family == distro_family


# ----------------------------------------------------------------------------
# Utilidades de borrado seguro
# ----------------------------------------------------------------------------

def dir_stats(paths: list[str], exclude: list[str] | None = None) -> ScanResult:
    """Tamaño y nº de archivos bajo cada ruta, ignorando enlaces simbólicos."""
    total = 0
    count = 0
    excluded = {os.path.realpath(p) for p in (exclude or [])}
    for path in paths:
        base = Path(path)
        if not base.exists():
            continue
        for root, dirs, files in os.walk(base, followlinks=False):
            # Ignora y no desciendas en carpetas excluidas (p. ej. la propia
            # caché de Linux Optimizer).
            dirs[:] = [
                d for d in dirs
                if os.path.realpath(os.path.join(root, d)) not in excluded
            ]
            for name in files:
                file_path = os.path.join(root, name)
                try:
                    st = os.lstat(file_path)
                    total += st.st_size
                    count += 1
                except OSError:
                    continue
    return ScanResult(size=total, files=count)


def delete_contents(paths: list[str], exclude: list[str] | None = None) -> CleanResult:
    """Elimina el CONTENIDO de cada ruta, nunca la ruta raíz."""
    result = CleanResult()
    excluded = {os.path.realpath(p) for p in (exclude or [])}
    for path in paths:
        base = Path(path)
        if not base.is_dir():
            continue
        for entry in sorted(base.iterdir()):
            try:
                if os.path.realpath(entry) in excluded:
                    continue
                size = _entry_size(entry)
                if entry.is_dir() and not entry.is_symlink():
                    shutil.rmtree(entry)
                else:
                    entry.unlink()
                result.freed += size
                result.removed += 1
            except FileNotFoundError:
                continue
            except OSError as exc:
                result.error = result.error or f"No se pudo borrar {entry}: {exc}"
    return result


def _entry_size(path: Path) -> int:
    try:
        if path.is_dir() and not path.is_symlink():
            total = 0
            for root, _dirs, files in os.walk(path, followlinks=False):
                for name in files:
                    try:
                        total += os.lstat(os.path.join(root, name)).st_size
                    except OSError:
                        pass
            return total
        return path.lstat().st_size
    except OSError:
        return 0


# ----------------------------------------------------------------------------
# Funciones de escaneo / limpieza
# ----------------------------------------------------------------------------

def _user_home_subdir(*parts: str) -> str:
    return str(Path.home().joinpath(*parts))


def _scan_user_cache() -> ScanResult:
    cache = _user_home_subdir(".cache")
    app_cache = _user_home_subdir(".cache", "LinuxOptimizer")
    return dir_stats([cache], exclude=[app_cache])


def _clean_user_cache() -> CleanResult:
    cache = _user_home_subdir(".cache")
    app_cache = _user_home_subdir(".cache", "LinuxOptimizer")
    return delete_contents([cache], exclude=[app_cache])


def _scan_thumbnails() -> ScanResult:
    return dir_stats([
        _user_home_subdir(".cache", "thumbnails"),
        _user_home_subdir(".thumbnails"),
    ])


def _scan_trash() -> ScanResult:
    return dir_stats([
        _user_home_subdir(".local", "share", "Trash", "files"),
        _user_home_subdir(".local", "share", "Trash", "info"),
    ])


def _clean_trash() -> CleanResult:
    return delete_contents([
        _user_home_subdir(".local", "share", "Trash", "files"),
        _user_home_subdir(".local", "share", "Trash", "info"),
    ])


def _parse_journal_usage(output: str) -> int:
    # Ej.: "Archived and active journals take up 1.2G in the file system."
    import re
    match = re.search(r"([\d.]+)\s*([KMGT]?i?B)", output)
    if not match:
        return 0
    value = float(match.group(1))
    unit = match.group(2).upper().replace("IB", "B")
    multiplier = {"B": 1, "KB": 10**3, "MB": 10**6, "GB": 10**9, "TB": 10**12,
                  "KIB": 2**10, "MIB": 2**20, "GIB": 2**30, "TIB": 2**40}
    return int(value * multiplier.get(unit, 1))


def _scan_journal() -> ScanResult:
    from linux_optimizer.core.permissions import run
    rc, out, err = run(["journalctl", "--disk-usage"], timeout=20)
    if rc != 0:
        return ScanResult(error=err.strip() or "journalctl no disponible")
    return ScanResult(size=_parse_journal_usage(out))


def _clean_journal() -> CleanResult:
    from linux_optimizer.core.permissions import run_privileged
    rc, out, err = run_privileged(["journalctl", "--vacuum-time=7d"], timeout=180)
    if rc != 0:
        return CleanResult(error=err.strip() or out.strip())
    return CleanResult(freed=0, removed=0, note="Se conservaron los últimos 7 días de registro")


def _clean_dnf_cache() -> CleanResult:
    from linux_optimizer.core.permissions import run_privileged
    rc, out, err = run_privileged(["dnf", "-y", "clean", "all"], timeout=180)
    if rc != 0:
        return CleanResult(error=err.strip() or out.strip())
    return CleanResult(note="Caché de dnf vaciada")


def _clean_apt_cache() -> CleanResult:
    from linux_optimizer.core.permissions import run_privileged
    rc, out, err = run_privileged(["apt-get", "clean"], timeout=180)
    if rc != 0:
        return CleanResult(error=err.strip() or out.strip())
    return CleanResult(note="Caché de apt vaciada")


def _clean_pacman_cache() -> CleanResult:
    from linux_optimizer.core.permissions import run_privileged
    # Conserva la versión más reciente de cada paquete.
    if shutil.which("paccache"):
        cmd = ["paccache", "-rk1"]
    else:
        cmd = ["pacman", "-Sc", "--noconfirm"]
    rc, out, err = run_privileged(cmd, timeout=300)
    if rc != 0:
        return CleanResult(error=err.strip() or out.strip())
    return CleanResult(note="Se conservó la versión más reciente de cada paquete")


def _clean_flatpak_unused() -> CleanResult:
    from linux_optimizer.core.permissions import run
    rc, out, err = run(["flatpak", "uninstall", "--unused", "-y"], timeout=600)
    if rc != 0:
        return CleanResult(error=err.strip() or out.strip())
    return CleanResult(note="Runtimes de flatpak sin uso eliminados")


def _flatpak_unused_scan() -> ScanResult:
    return ScanResult(note="flatpak calculará los runtimes sin uso al ejecutar la limpieza")


# ----------------------------------------------------------------------------
# Construcción de objetivos
# ----------------------------------------------------------------------------

def build_targets(distro_family: str) -> list[CleanTarget]:
    home_cache = _user_home_subdir(".cache")
    targets = [
        CleanTarget(
            key="user_cache",
            title="Caché de usuario (~/.cache)",
            description="Datos temporales regenerables de aplicaciones y del escritorio.",
            needs_root=False,
            scan=_scan_user_cache,
            clean=_clean_user_cache,
        ),
        CleanTarget(
            key="thumbnails",
            title="Miniaturas de archivos",
            description=f"Miniaturas antiguas en {home_cache}/thumbnails.",
            needs_root=False,
            scan=_scan_thumbnails,
            clean=lambda: delete_contents([
                _user_home_subdir(".cache", "thumbnails"),
                _user_home_subdir(".thumbnails"),
            ]),
        ),
        CleanTarget(
            key="trash",
            title="Papelera de reciclaje",
            description="Archivos eliminados que siguen ocupando espacio.",
            needs_root=False,
            scan=_scan_trash,
            clean=_clean_trash,
        ),
        CleanTarget(
            key="journal",
            title="Registros del sistema (journal)",
            description="Mantiene solo los últimos 7 días de journald. Requiere privilegios.",
            needs_root=True,
            scan=_scan_journal,
            clean=_clean_journal,
        ),
        CleanTarget(
            key="flatpak_unused",
            title="Runtimes flatpak sin uso",
            description="flatpak uninstall --unused: elimina runtimes que ninguna app usa.",
            needs_root=False,
            scan=_flatpak_unused_scan,
            clean=_clean_flatpak_unused,
        ),
    ]

    pkg = {
        "fedora": CleanTarget(
            key="pkg_cache",
            title="Caché del gestor de paquetes (dnf)",
            description="Vacia /var/cache/dnf. Los paquetes instalados no se tocan.",
            needs_root=True,
            family="fedora",
            scan=lambda: _scan_root_dir("/var/cache/dnf"),
            clean=_clean_dnf_cache,
        ),
        "debian": CleanTarget(
            key="pkg_cache",
            title="Caché del gestor de paquetes (apt)",
            description="Vacia /var/cache/apt/archives (.deb descargados).",
            needs_root=True,
            family="debian",
            scan=lambda: _scan_root_dir("/var/cache/apt/archives"),
            clean=_clean_apt_cache,
        ),
        "arch": CleanTarget(
            key="pkg_cache",
            title="Caché del gestor de paquetes (pacman)",
            description="Conserva solo la versión más reciente de cada paquete en caché.",
            needs_root=True,
            family="arch",
            scan=lambda: _scan_root_dir("/var/cache/pacman/pkg"),
            clean=_clean_pacman_cache,
        ),
    }
    target = pkg.get(distro_family)
    if target:
        targets.append(target)
    return targets


def _scan_root_dir(path: str) -> ScanResult:
    if os.path.isdir(path):
        return dir_stats([path])
    return ScanResult(note="El directorio no existe en este sistema")
