"""Ejecución de comandos: siempre explícita, nunca automática.

`run` ejecuta comandos de solo lectura o de mantenimiento con timeout.
`run_privileged` eleva con pkexec (polkit), pidiendo contraseña al usuario
gráficamente; la aplicación nunca ejecuta acciones destructivas sin que
el usuario haya confirmado previamente en un diálogo.
"""

from __future__ import annotations

import logging
import shutil
import subprocess

from linux_optimizer import APP_NAME

log = logging.getLogger(APP_NAME.replace(" ", "."))
def which(binary: str) -> str | None:
    return shutil.which(binary)


def run(
    cmd: list[str],
    timeout: float = 15.0,
    check: bool = False,
) -> tuple[int, str, str]:
    """Ejecuta un comando como el usuario actual. Nunca usa shell=True."""
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        return proc.returncode, proc.stdout, proc.stderr
    except FileNotFoundError:
        return 127, "", f"comando no encontrado: {cmd[0]}"
    except subprocess.TimeoutExpired:
        return 124, "", f"tiempo agotado: {' '.join(cmd)}"
    except OSError as exc:
        return 1, "", str(exc)


def run_privileged(cmd: list[str], timeout: float = 120.0) -> tuple[int, str, str]:
    """Ejecuta un comando elevando privilegios con pkexec.

    El agente de polkit pedirá la contraseña al usuario de forma gráfica.
    Devuelve (rc, stdout, stderr); rc=126 suele indicar que el usuario
    canceló la autenticación.
    """
    pkexec = which("pkexec")
    if not pkexec:
        return 127, "", (
            "No se encontró pkexec (polkit). Instálalo o ejecuta la "
            "aplicación desde una sesión con polkit disponible."
        )
    rc, out, err = run([pkexec, "--disable-internal-agent", *cmd], timeout=timeout)
    if rc == 0:
        log.info("pkexec OK: %s", cmd[0])
    else:
        log.warning("pkexec rc=%s cmd=%s err=%s", rc, cmd[0], err.strip()[:300])
        err = f"{err.strip()} (pkexec rc={rc})"
    return rc, out, err


def is_cancelled(stderr: str) -> bool:
    """True si el usuario canceló la autenticación de polkit."""
    low = stderr.lower()
    return "not authorized" in low or "dismissed" in low or "cancel" in low


def user_error(message: str) -> str:
    """Mensaje amigable para errores de ejecución."""
    if "comando no encontrado" in message:
        return f"Comando no disponible en este sistema ({APP_NAME} lo detectó automáticamente)."
    return message
