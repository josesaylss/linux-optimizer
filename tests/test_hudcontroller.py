"""Pruebas de la aparición automática del HUD con los juegos."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication  # noqa: E402

from linux_optimizer.ui.hud_controller import HudController  # noqa: E402


@pytest.fixture(scope="module")
def app():
    yield QApplication.instance() or QApplication([])


def _fake_controller(monkeypatch):
    hud = HudController()
    hud._auto_timer.stop()
    hud.auto_enabled = True
    hud._suppress = False
    state = {"running": False, "calls": []}

    monkeypatch.setattr(hud, "is_running", lambda: state["running"])

    def fake_show():
        state["calls"].append("show")
        state["running"] = True

    def fake_auto_hide():
        state["calls"].append("hide")
        state["running"] = False
        hud._auto_started = False

    monkeypatch.setattr(hud, "show", fake_show)
    monkeypatch.setattr(hud, "_auto_hide", fake_auto_hide)
    return hud, state


def test_auto_show_with_fresh_game(app, monkeypatch):
    hud, state = _fake_controller(monkeypatch)
    monkeypatch.setattr(hud, "_game_is_running", lambda: True)
    hud._auto_tick()
    assert state["calls"] == ["show"]
    assert hud._auto_started


def test_auto_hide_when_game_ends(app, monkeypatch):
    hud, state = _fake_controller(monkeypatch)
    monkeypatch.setattr(hud, "_game_is_running", lambda: True)
    hud._auto_tick()
    state["calls"].clear()

    monkeypatch.setattr(hud, "_game_is_running", lambda: False)
    for _ in range(5):
        hud._auto_tick()
    assert state["calls"] == ["hide"]
    assert not hud._auto_started


def test_manual_close_is_respected(app, monkeypatch):
    hud, state = _fake_controller(monkeypatch)
    hud._suppress = True  # el usuario pulsó ✕
    monkeypatch.setattr(hud, "_game_is_running", lambda: True)
    for _ in range(3):
        hud._auto_tick()
    assert state["calls"] == []
