"""Tema oscuro de la aplicación (Qt Stylesheets)."""

from __future__ import annotations

import pathlib

_THEME_PATH = pathlib.Path(__file__).with_name("style.qss")


def _load() -> str:
    try:
        return _THEME_PATH.read_text(encoding="utf-8")
    except OSError:
        return ""


THEME_QSS = _load()
