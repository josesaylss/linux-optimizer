"""Game Booster de Cortex Gaming Engine.

En Linux detecta el juego activo por el registro de MangoHud y prioriza su
proceso (``nice`` negativo + prioridad de E/S) con un único pkexec. En Windows
busca juegos en las carpetas habituales (Steam, Epic, GOG…) o en procesos con
ventana visible y les asigna prioridad Alta con psutil. Es una acción puntual
y reversible: guarda la prioridad original para restaurarla.
"""

from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path

import psutil

from linux_optimizer.core import platform_info
from linux_optimizer.core.cleaner import _parse_batch_output, build_batch_script
from linux_optimizer.core.gamehud import MANGO_LOG_DIR, find_latest_log
from linux_optimizer.core.permissions import run_privileged

from cortex_engine.config import state_dir

GAME_STALE_SECS = 5.0
BOOST_NICE = -5

# Procesos que nunca son un juego (lanzadores, navegadores, herramientas).
_WINDOWS_IGNORED = {
    "linuxoptimizer.exe", "python.exe", "pythonw.exe",
    "steam.exe", "steamwebhelper.exe", "steamservice.exe",
    "epicgameslauncher.exe", "epicwebhelper.exe",
    "galaxyclient.exe", "galaxyclientservice.exe",
    "battle.net.exe", "agent.exe", "blizzard error.exe",
    "riotclientservices.exe", "riotclientcrashhandler.exe",
    "origin.exe", "eaapp.exe", "eadesktop.exe", "ubisoftconnect.exe",
    "uplay.exe", "upc.exe", "discord.exe", "discordptb.exe",
    "chrome.exe", "msedge.exe", "firefox.exe", "opera.exe", "brave.exe",
    "vivaldi.exe", "explorer.exe", "searchhost.exe", "shellexperiencehost.exe",
    "applicationframehost.exe", "startmenuexperiencehost.exe",
    "windowsterminal.exe", "conhost.exe", "cmd.exe", "powershell.exe",
    "pwsh.exe", "code.exe", "devenv.exe", "notepad.exe", "taskmgr.exe",
    "systemsettings.exe", "securityhealthsystray.exe",
}

# Carpetas típicas de juegos instalados en Windows.
_WINDOWS_GAME_HINTS = (
    "steamapps\\common", "epic games", "gog galaxy\\games", "gog games",
    "riot games", "ubisoft game launcher\\games", "ea games",
    "origin games", "xboxgames", "\\games\\",
)


def _windows_visible_pids() -> set[int]:
    """PIDs con una ventana visible y con título (solo Windows)."""
    if not platform_info.IS_WINDOWS:
        return set()
    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.WinDLL("user32", use_last_error=True)
        pids: set[int] = set()

        @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        def _callback(hwnd, _lparam):
            if user32.IsWindowVisible(hwnd) and user32.GetWindowTextLengthW(hwnd):
                pid = wintypes.DWORD()
                user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                if pid.value:
                    pids.add(int(pid.value))
            return True

        user32.EnumWindows(_callback, 0)
        return pids
    except (OSError, AttributeError):
        return set()


def game_name_from_log(path: Path) -> str:
    """``juego_2026-11-19_20-00-00.csv`` → ``juego``."""
    stem = path.stem
    parts = stem.rsplit("_", 2)
    return parts[0] if len(parts) == 3 else stem


def _normalize(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()


class GameBooster:
    def __init__(self, state_path: Path | None = None,
                 log_dir: Path | None = None, activity=None):
        self.state_path = (Path(state_path) if state_path is not None
                           else state_dir() / "booster.json")
        self.log_dir = Path(log_dir) if log_dir is not None else MANGO_LOG_DIR
        self.activity = activity
        self._windows_cache: tuple[float, dict | None] = (0.0, None)

    # ------------------------------------------------------------------
    # Detección
    # ------------------------------------------------------------------

    def active_game(self) -> dict | None:
        if platform_info.IS_WINDOWS:
            process = self._windows_game_process()
            if process is None:
                return None
            return {
                "name": process["name"],
                "pid": process["pid"],
                "age_secs": 0,
            }
        latest = find_latest_log(self.log_dir)
        if latest is None:
            return None
        try:
            age = time.time() - latest.stat().st_mtime
        except OSError:
            return None
        if age >= GAME_STALE_SECS:
            return None
        return {
            "name": game_name_from_log(latest),
            "log": latest,
            "age_secs": age,
        }

    def candidates(self, game_name: str) -> list[dict]:
        tokens = [t for t in _normalize(game_name).split() if len(t) >= 3]
        if not tokens:
            return []
        found: list[dict] = []
        me = os.getpid()
        for proc in psutil.process_iter(
                ["pid", "name", "nice", "cmdline", "memory_info"]):
            try:
                info = proc.info
                pid = info.get("pid")
                if not pid or pid == me:
                    continue
                haystack = _normalize(
                    f"{info.get('name') or ''} "
                    f"{' '.join(info.get('cmdline') or [])}")
                if not any(token in haystack for token in tokens):
                    continue
                memory = info.get("memory_info")
                found.append({
                    "pid": pid,
                    "name": info.get("name") or "",
                    "nice": info.get("nice") or 0,
                    "rss": memory.rss if memory else 0,
                })
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        found.sort(key=lambda item: item["rss"], reverse=True)
        return found

    def _windows_game_process(self) -> dict | None:
        """Mejor proceso de juego en Windows (con caché de 2 segundos)."""
        now = time.monotonic()
        cached_at, cached = self._windows_cache
        if now - cached_at < 2.0:
            return cached

        visible = _windows_visible_pids()
        me = os.getpid()
        found: list[dict] = []
        for proc in psutil.process_iter(
                ["pid", "name", "exe", "nice", "memory_info"]):
            try:
                info = proc.info
                pid = int(info.get("pid") or 0)
                name = info.get("name") or ""
                if not pid or pid == me or name.lower() in _WINDOWS_IGNORED:
                    continue
                exe = (info.get("exe") or "")
                lowered = exe.lower().replace("/", "\\")
                in_game_dir = any(hint in lowered for hint in _WINDOWS_GAME_HINTS)
                if not in_game_dir and pid not in visible:
                    continue
                memory = info.get("memory_info")
                found.append({
                    "pid": pid,
                    "name": name,
                    "nice": info.get("nice") or 0,
                    "rss": memory.rss if memory else 0,
                    "game_dir": in_game_dir,
                })
            except (psutil.NoSuchProcess, psutil.AccessDenied, ValueError):
                continue
        found.sort(key=lambda item: (item["game_dir"], item["rss"]),
                   reverse=True)
        result = found[0] if found else None
        self._windows_cache = (now, result)
        return result

    def find_process(self) -> dict | None:
        if platform_info.IS_WINDOWS:
            return self._windows_game_process()
        game = self.active_game()
        if not game:
            return None
        matches = self.candidates(game["name"])
        return matches[0] if matches else None

    def list_processes(self, limit: int = 80) -> list[dict]:
        """Procesos candidatos para selección manual (plan B).

        Se ordena por probabilidad de ser un juego: carpeta de juegos o
        ventana visible primero, después consumo de memoria. Nunca incluye
        la propia aplicación.
        """
        visible = _windows_visible_pids() if platform_info.IS_WINDOWS else set()
        me = os.getpid()
        found: list[dict] = []
        for proc in psutil.process_iter(
                ["pid", "name", "exe", "nice", "memory_info"]):
            try:
                info = proc.info
                pid = int(info.get("pid") or 0)
                name = info.get("name") or ""
                if not pid or pid == me or name.lower() in _WINDOWS_IGNORED:
                    continue
                exe = info.get("exe") or ""
                lowered = exe.lower().replace("/", "\\")
                game_dir = any(hint in lowered
                               for hint in _WINDOWS_GAME_HINTS)
                memory = info.get("memory_info")
                rss = memory.rss if memory else 0
                found.append({
                    "pid": pid,
                    "name": name,
                    "nice": info.get("nice") or 0,
                    "rss": rss,
                    "visible": pid in visible,
                    "game_dir": game_dir,
                    "label": (f"{name} · PID {pid} · {rss / 1e6:.0f} MB"),
                })
            except (psutil.NoSuchProcess, psutil.AccessDenied, ValueError):
                continue
        found.sort(key=lambda item: (item["game_dir"], item["visible"],
                                     item["rss"]), reverse=True)
        return found[:limit]

    # ------------------------------------------------------------------
    # Priorización
    # ------------------------------------------------------------------

    def boosted(self) -> dict | None:
        try:
            data = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if not isinstance(data, dict) or "pid" not in data:
            return None
        try:
            if not psutil.pid_exists(int(data["pid"])):
                self.state_path.unlink(missing_ok=True)
                return None
        except (TypeError, ValueError):
            return None
        return data

    def _process_by_pid(self, pid: int) -> dict | None:
        if pid <= 0 or pid == os.getpid():
            return None
        try:
            info = psutil.Process(pid).as_dict(
                ["pid", "name", "nice", "memory_info"])
        except (psutil.Error, OSError, ValueError):
            return None
        memory = info.get("memory_info")
        return {
            "pid": pid,
            "name": info.get("name") or f"PID {pid}",
            "nice": info.get("nice") or 0,
            "rss": memory.rss if memory else 0,
        }

    def boost(self, pid: int | None = None) -> tuple[bool, str]:
        if pid is None:
            process = self.find_process()
        else:
            process = self._process_by_pid(int(pid))
            if process is None:
                return False, (f"El proceso {pid} ya no está en ejecución. "
                               "Actualiza la lista e inténtalo de nuevo.")
        if process is None:
            hint = ("Abre el juego (Steam, Epic, GOG o una ventana de juego) "
                    "e inténtalo de nuevo, o elige el proceso manualmente."
                    if platform_info.IS_WINDOWS else
                    "Abre el juego con MangoHud activo o elige el proceso "
                    "manualmente.")
            return False, "No se pudo identificar el proceso del juego. " + hint
        if self.boosted():
            return False, "Ya hay un juego priorizado."
        if platform_info.IS_WINDOWS:
            return self._boost_windows(process)
        pid = int(process["pid"])
        old_nice = int(process["nice"])
        command = (
            f"renice -n {BOOST_NICE} -p {pid}; "
            f"command -v ionice >/dev/null 2>&1 && "
            f"ionice -c 2 -n 0 -p {pid} || true"
        )
        rc, out, err = run_privileged(
            ["bash", "-c", build_batch_script([("booster", command)])],
            timeout=60,
        )
        parsed = _parse_batch_output(out)
        if parsed.get("booster") != 0:
            message = err.strip() or f"pkexec rc={rc}"
            self._log(f"No se pudo priorizar «{process['name']}»: {message}",
                      "ERROR")
            return False, message
        self._save_state(pid, process["name"], old_nice)
        self._log(f"Juego priorizado: «{process['name']}» (PID {pid})", "OK")
        return True, f"«{process['name']}» priorizado (nice {BOOST_NICE})."

    def unboost(self) -> tuple[bool, str]:
        data = self.boosted()
        if data is None:
            return True, "No hay ningún juego priorizado."
        if platform_info.IS_WINDOWS:
            return self._unboost_windows(data)
        pid = int(data["pid"])
        old_nice = int(data.get("old_nice", 0))
        command = (
            f"renice -n {old_nice} -p {pid} 2>/dev/null; "
            f"command -v ionice >/dev/null 2>&1 && "
            f"ionice -c 2 -n 4 -p {pid} 2>/dev/null || true"
        )
        rc, out, err = run_privileged(
            ["bash", "-c", build_batch_script([("booster", command)])],
            timeout=60,
        )
        parsed = _parse_batch_output(out)
        if parsed.get("booster") not in (0, None):
            message = err.strip() or f"pkexec rc={rc}"
            self._log(f"No se pudo quitar la prioridad: {message}", "ERROR")
            return False, message
        self.state_path.unlink(missing_ok=True)
        self._log(f"Prioridad retirada a «{data.get('name', 'juego')}»", "OK")
        return True, "Prioridad restaurada."

    # ------------------------------------------------------------------
    # Windows: prioridad de proceso nativa (sin pkexec)
    # ------------------------------------------------------------------

    def _save_state(self, pid: int, name: str, old_nice: int) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(
            json.dumps({
                "pid": pid,
                "name": name,
                "old_nice": old_nice,
                "boosted_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                "platform": "windows" if platform_info.IS_WINDOWS else "linux",
            }, indent=2) + "\n",
            encoding="utf-8",
        )

    def _boost_windows(self, process: dict) -> tuple[bool, str]:
        pid = int(process["pid"])
        try:
            proc = psutil.Process(pid)
            old_nice = int(proc.nice())
            proc.nice(getattr(psutil, "HIGH_PRIORITY_CLASS", 128))
        except (psutil.Error, OSError, ValueError) as exc:
            self._log(f"No se pudo priorizar «{process['name']}»: {exc}",
                      "ERROR")
            return False, f"No se pudo priorizar el juego: {exc}"
        self._save_state(pid, process["name"], old_nice)
        self._log(f"Juego priorizado: «{process['name']}» (PID {pid})", "OK")
        return True, f"«{process['name']}» priorizado (prioridad alta)."

    def _unboost_windows(self, data: dict) -> tuple[bool, str]:
        pid = int(data["pid"])
        old_nice = int(data.get("old_nice", getattr(
            psutil, "NORMAL_PRIORITY_CLASS", 32)))
        try:
            psutil.Process(pid).nice(old_nice)
        except psutil.NoSuchProcess:
            pass
        except (psutil.Error, OSError, ValueError) as exc:
            self._log(f"No se pudo quitar la prioridad: {exc}", "ERROR")
            return False, f"No se pudo restaurar la prioridad: {exc}"
        self.state_path.unlink(missing_ok=True)
        self._log(f"Prioridad retirada a «{data.get('name', 'juego')}»", "OK")
        return True, "Prioridad restaurada."

    # ------------------------------------------------------------------

    def _log(self, message: str, level: str = "INFO") -> None:
        if self.activity is not None:
            self.activity.log(message, level)
