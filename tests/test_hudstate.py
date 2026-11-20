"""Pruebas de las preferencias persistentes del HUD."""

from linux_optimizer.core.hudstate import DEFAULT_STATE, load_state, save_state


def test_load_defaults_when_missing(tmp_path):
    assert load_state(tmp_path / "no-existe.json") == DEFAULT_STATE


def test_save_load_roundtrip(tmp_path):
    path = tmp_path / "hud.json"
    save_state({"x": 120, "y": 80, "locked": True}, path)
    assert load_state(path) == {
        "x": 120, "y": 80, "locked": True, "auto_show": True}


def test_auto_show_is_preserved(tmp_path):
    path = tmp_path / "hud.json"
    save_state({"x": 1, "y": 2, "locked": False, "auto_show": False}, path)
    assert load_state(path)["auto_show"] is False


def test_load_ignores_corrupt_file(tmp_path):
    path = tmp_path / "hud.json"
    path.write_text("{esto no es json")
    assert load_state(path) == DEFAULT_STATE


def test_save_creates_parent_dirs(tmp_path):
    path = tmp_path / "a" / "b" / "hud.json"
    save_state({"x": 1, "y": 2, "locked": False}, path)
    assert path.exists()
    assert load_state(path)["x"] == 1
