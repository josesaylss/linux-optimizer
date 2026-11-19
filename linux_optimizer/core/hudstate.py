"""Preferencias persistentes del HUD (posición y bloqueo).

Se guardan en un JSON pequeño dentro de ~/.local/state/LinuxOptimizer para
que el HUD recuerde dónde lo dejó el usuario y si estaba fijado.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

STATE_PATH = Path.home() / ".local/state/LinuxOptimizer/hud.json"
DEFAULT_STATE = {"x": None, "y": None, "locked": False}


def load_state(path: Path = STATE_PATH) -> dict:
    """Devuelve el estado guardado; valores por defecto si no existe o falla."""
    state = dict(DEFAULT_STATE)
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return state
    if isinstance(data, dict):
        for key in DEFAULT_STATE:
            if key in data:
                state[key] = data[key]
    return state


def save_state(state: dict, path: Path = STATE_PATH) -> None:
    """Guarda posición y bloqueo de forma atómica (ignora errores de disco)."""
    payload = {key: state.get(key, DEFAULT_STATE[key]) for key in DEFAULT_STATE}
    tmp = path.with_suffix(".tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(payload, fh)
        os.replace(tmp, path)
    except OSError:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
