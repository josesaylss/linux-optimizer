"""Game Booster de Cortex Gaming Engine.

Detecta el juego activo por el registro de MangoHud y prioriza su proceso
(``nice`` negativo + prioridad de E/S) con un único pkexec. Es una acción
puntual y reversible: guarda el ``nice`` original para restaurarlo.
"""

from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path

import psutil

from linux_optimizer.core.cleaner import _parse_batch_output, build_batch_script
from linux_optimizer.core.gamehud import MANGO_LOG_DIR, find_latest_log
from linux_optimizer.core.permissions import run_privileged

from cortex_engine.config import state_dir

GAME_STALE_SECS = 5.0
BOOST_NICE = -5


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

    # ------------------------------------------------------------------
    # Detección
    # ------------------------------------------------------------------

    def active_game(self) -> dict | None:
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

    def find_process(self) -> dict | None:
        game = self.active_game()
        if not game:
            return None
        matches = self.candidates(game["name"])
        return matches[0] if matches else None

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

    def boost(self) -> tuple[bool, str]:
        process = self.find_process()
        if process is None:
            return False, ("No se pudo identificar el proceso del juego. "
                           "Abre el juego con MangoHud activo e inténtalo de nuevo.")
        if self.boosted():
            return False, "Ya hay un juego priorizado."
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
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(
            json.dumps({
                "pid": pid,
                "name": process["name"],
                "old_nice": old_nice,
                "boosted_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            }, indent=2) + "\n",
            encoding="utf-8",
        )
        self._log(f"Juego priorizado: «{process['name']}» (PID {pid})", "OK")
        return True, f"«{process['name']}» priorizado (nice {BOOST_NICE})."

    def unboost(self) -> tuple[bool, str]:
        data = self.boosted()
        if data is None:
            return True, "No hay ningún juego priorizado."
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

    def _log(self, message: str, level: str = "INFO") -> None:
        if self.activity is not None:
            self.activity.log(message, level)
