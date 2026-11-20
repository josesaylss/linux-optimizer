"""Pruebas de la captura global de FPS (MangoHud para toda la sesión)."""

from pathlib import Path

from linux_optimizer.core import globalfps


def test_disabled_by_default(tmp_path):
    assert not globalfps.global_fps_enabled(tmp_path / "no-existe.conf")


def test_enable_writes_env_file(tmp_path, monkeypatch):
    monkeypatch.setattr(globalfps, "ensure_mangolog_dir",
                        lambda: tmp_path / "logs")
    env = tmp_path / "env" / "90-fps.conf"
    globalfps.set_global_fps(True, path=env, log_dir=tmp_path / "logs")

    text = env.read_text(encoding="utf-8")
    assert "MANGOHUD=1" in text
    config = globalfps.mangohud_config(tmp_path / "logs")
    assert f"MANGOHUD_CONFIG={config}" in text
    assert "autostart_log=1" in config
    assert "output_folder=" in config
    assert globalfps.global_fps_enabled(env)


def test_disable_removes_env_file(tmp_path, monkeypatch):
    monkeypatch.setattr(globalfps, "ensure_mangolog_dir",
                        lambda: tmp_path / "logs")
    env = tmp_path / "90-fps.conf"
    globalfps.set_global_fps(True, path=env, log_dir=tmp_path / "logs")
    globalfps.set_global_fps(False, path=env)
    assert not env.exists()
    assert not globalfps.global_fps_enabled(env)


def test_overlay_hidden_offscreen(tmp_path):
    config = globalfps.mangohud_config(tmp_path)
    # no_display también apaga el registro; el overlay se aparta en su lugar.
    assert "no_display" not in config
    assert "offset_x=9000" in config
    assert "offset_y=9000" in config
