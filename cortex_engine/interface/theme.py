"""Tema visual propio de Cortex Gaming Engine (oscuro con acentos verdes)."""

from __future__ import annotations

from pathlib import Path

_PATH = Path(__file__).with_name("theme.qss")


def _load() -> str:
    try:
        return _PATH.read_text(encoding="utf-8")
    except OSError:
        return ""


CORTEX_QSS = _load()
