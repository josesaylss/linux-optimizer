"""Captura de FPS global con MangoHud (todos los juegos y apps).

MangoHud se activa con la variable de entorno ``MANGOHUD=1``. Al escribirla
en ``~/.config/environment.d`` (junto con la carpeta de registros), **cualquier
aplicación Vulkan** de la sesión —incluidos los juegos Proton/DXVK— escribe su
registro de FPS sin tener que lanzarla a mano. El HUD lee ese registro.

Detalles:

* ``offset_x/offset_y`` enormes empujan el overlay propio de MangoHud fuera de
  la pantalla: solo interesa su registro, porque el HUD de Linux Optimizer ya
  muestra los datos. (``no_display`` desactiva también el registro, por eso no
  se usa.)
* Los juegos OpenGL necesitan el envoltorio ``mangohud``; el archivo de
  entorno no puede precargar la librería en toda la sesión sin riesgo.
"""

from __future__ import annotations

import os
from pathlib import Path

from linux_optimizer.core.gamehud import MANGO_LOG_DIR, ensure_mangolog_dir

ENV_FILENAME = "90-linux-optimizer-fps.conf"
DEFAULT_ENV_PATH = Path.home() / ".config/environment.d" / ENV_FILENAME


def env_path(path: Path | None = None) -> Path:
    return Path(path) if path is not None else DEFAULT_ENV_PATH


def mangohud_config(log_dir: Path | str | None = None) -> str:
    """Valor de MANGOHUD_CONFIG: registra FPS y oculta el overlay propio."""
    directory = Path(log_dir) if log_dir is not None else MANGO_LOG_DIR
    return (
        f"output_folder={directory},autostart_log=1,log_interval=100,"
        "offset_x=9000,offset_y=9000"
    )


def global_fps_enabled(path: Path | None = None) -> bool:
    """¿Está activada la captura global para esta sesión de usuario?"""
    try:
        text = env_path(path).read_text(encoding="utf-8")
    except OSError:
        return False
    return "MANGOHUD=1" in text.replace(" ", "")


def set_global_fps(enabled: bool, path: Path | None = None,
                   log_dir: Path | str | None = None) -> Path:
    """Activa o desactiva la captura global escribiendo el archivo de entorno."""
    target = env_path(path)
    if not enabled:
        try:
            target.unlink()
        except FileNotFoundError:
            pass
        return target
    ensure_mangolog_dir()
    target.parent.mkdir(parents=True, exist_ok=True)
    content = (
        "# Generado por Linux Optimizer: captura de FPS en todos los juegos.\n"
        "# Se aplica al iniciar sesión (systemd --user).\n"
        "MANGOHUD=1\n"
        f"MANGOHUD_CONFIG={mangohud_config(log_dir)}\n"
    )
    tmp = target.with_suffix(".tmp")
    tmp.write_text(content, encoding="utf-8")
    os.replace(tmp, target)
    return target
