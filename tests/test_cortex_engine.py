"""Pruebas de Cortex Gaming Engine: módulos, perfiles, configuración y GUI."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import json  # noqa: E402
from pathlib import Path  # noqa: E402

import pytest  # noqa: E402

from cortex_engine.config import PROFILE_KEYS, CortexConfig  # noqa: E402
from cortex_engine.cpu.module import CpuModule  # noqa: E402
from cortex_engine.gaming.booster import game_name_from_log  # noqa: E402
from cortex_engine.gpu.module import GpuModule  # noqa: E402
from cortex_engine.memory.module import MemoryModule  # noqa: E402
from cortex_engine.monitoring.activity import ActivityLog  # noqa: E402
from cortex_engine.profiles.manager import (  # noqa: E402
    PROFILE_MAP,
    ProfileManager,
    apply_commands,
)
from cortex_engine.restore.store import RestoreStore  # noqa: E402


# ----------------------------------------------------------------------------
# Estructura y configuración
# ----------------------------------------------------------------------------

def test_required_structure_exists():
    root = Path(__file__).resolve().parents[1] / "cortex_engine"
    for folder in ("interface", "cpu", "gpu", "memory", "gaming",
                   "monitoring", "profiles", "restore"):
        assert (root / folder).is_dir()
        assert (root / folder / "__init__.py").is_file()
    assert (root / "main.py").is_file()


def test_profiles_are_eco_balanced_extreme():
    assert PROFILE_KEYS == ("eco", "balanced", "extreme")
    assert set(PROFILE_MAP) == set(PROFILE_KEYS)
    for profile in PROFILE_MAP.values():
        assert profile.title
        assert profile.description


def test_config_defaults_and_validation(tmp_path):
    config = CortexConfig(path=tmp_path / "cortex.json")
    assert config.get("monitor_interval_ms") == 1500
    assert config.get("profile") == ""
    config.set("monitor_interval_ms", 100)
    assert config.get("monitor_interval_ms") == 500
    config.set("monitor_interval_ms", 999999)
    assert config.get("monitor_interval_ms") == 10000
    config.set("profile", "inventado")
    assert config.get("profile") == ""
    config.save()
    assert json.loads((tmp_path / "cortex.json").read_text())["version"] == 1


def test_config_export_import_roundtrip(tmp_path):
    source = CortexConfig(path=tmp_path / "source.json")
    source.set("profile", "balanced")
    source.set("monitor_interval_ms", 2000)
    source.set("auto_detect_game", False)
    exported = source.export_to(tmp_path / "export.json")
    payload = json.loads(exported.read_text())
    assert payload["exported_by"].startswith("Cortex Gaming Engine")

    target = CortexConfig(path=tmp_path / "target.json")
    keys = target.import_from(exported)
    assert "profile" in keys
    assert target.get("profile") == "balanced"
    assert target.get("monitor_interval_ms") == 2000
    assert target.get("auto_detect_game") is False

    bad = tmp_path / "bad.json"
    bad.write_text("[]", encoding="utf-8")
    with pytest.raises(ValueError):
        target.import_from(bad)


def test_restore_store_atomic_and_info(tmp_path):
    store = RestoreStore(path=tmp_path / "restore.json")
    assert not store.exists()
    store.save({"cpu": {"governor": "powersave"}})
    assert store.exists()
    data = store.load()
    assert data["cpu"]["governor"] == "powersave"
    assert "guardados" in store.info()
    store.clear()
    assert not store.exists()
    assert store.load() is None


# ----------------------------------------------------------------------------
# Módulos de hardware (con árboles sysfs falsos)
# ----------------------------------------------------------------------------

def _make_cpu_tree(root: Path) -> None:
    for index in range(2):
        cpufreq = root / f"cpu{index}" / "cpufreq"
        cpufreq.mkdir(parents=True)
        (cpufreq / "scaling_governor").write_text("powersave\n")
        (cpufreq / "energy_performance_preference").write_text("balance_power\n")
    (root / "cpufreq").mkdir()
    (root / "cpufreq" / "boost").write_text("0\n")
    (root / "cpu0" / "cpufreq" / "scaling_available_governors").write_text(
        "powersave performance schedutil\n")
    (root / "cpu0" / "cpufreq" /
     "energy_performance_available_preferences").write_text(
        "power balance_power balance_performance performance\n")


def test_cpu_module_profiles_and_revert(tmp_path):
    root = tmp_path / "cpu"
    _make_cpu_tree(root)
    cpu = CpuModule(root)

    state = cpu.state()
    assert state["governor"] == "powersave"
    assert state["cpus"] == 2
    assert state["boost"] == "no"

    extreme = {key: (cmd, label) for key, cmd, label in cpu.commands("extreme")}
    assert "performance" in extreme["cpu_governor"][0]
    assert "performance" in extreme["cpu_epp"][0]
    assert "echo 1 >" in extreme["cpu_boost"][0]

    eco = {key: (cmd, label) for key, cmd, label in cpu.commands("eco")}
    assert "powersave" in eco["cpu_governor"][0]
    assert "power" in eco["cpu_epp"][0]
    assert "echo 0 >" in eco["cpu_boost"][0]

    snapshot = cpu.snapshot()
    assert snapshot["governor"]
    revert = cpu.revert_commands(snapshot)
    assert {key for key, _cmd, _label in revert} == {
        "cpu_governor", "cpu_epp", "cpu_boost"}
    assert "powersave" in revert[0][1]


def test_cpu_module_uses_fallback_governor(tmp_path):
    root = tmp_path / "cpu"
    (root / "cpu0" / "cpufreq").mkdir(parents=True)
    (root / "cpu0" / "cpufreq" / "scaling_governor").write_text("ondemand\n")
    (root / "cpu0" / "cpufreq" / "scaling_available_governors").write_text(
        "powersave ondemand performance\n")
    cpu = CpuModule(root)
    balanced = {key: cmd for key, cmd, _label in cpu.commands("balanced")}
    assert "schedutil" not in balanced["cpu_governor"]
    assert "ondemand" in balanced["cpu_governor"]


def test_gpu_module_amd_and_intel(tmp_path):
    root = tmp_path / "drm"
    amd = root / "card0" / "device"
    amd.mkdir(parents=True)
    (amd / "power_dpm_force_performance_level").write_text("auto\n")
    intel = root / "card1" / "device"
    intel.mkdir(parents=True)
    (intel / "gt_max_freq_mhz").write_text("1000\n")
    (intel / "gt_RP0_freq_mhz").write_text("1300\n")
    (intel / "gt_RP1_freq_mhz").write_text("300\n")

    gpu = GpuModule(root, gpus=[])
    extreme = {key: cmd for key, cmd, _label in gpu.commands("extreme")}
    assert "high" in extreme["gpu_amd"]
    assert "1300" in extreme["gpu_intel"]

    eco = {key: cmd for key, cmd, _label in gpu.commands("eco")}
    assert "low" in eco["gpu_amd"]
    assert "300" in eco["gpu_intel"]

    snapshot = gpu.snapshot()
    revert = {key: cmd for key, cmd, _label in gpu.revert_commands(snapshot)}
    assert "auto" in revert["gpu_amd"]
    assert "1000" in revert["gpu_intel"]


def test_gpu_module_notes_nvidia():
    from linux_optimizer.core.hardware import GPUInfo

    gpu = GpuModule(gpus=[GPUInfo(name="NVIDIA GeForce", vendor="nvidia",
                                  driver="nvidia")])
    notes = gpu.notes()
    assert any("NVIDIA" in note for note in notes)


def test_memory_module_profiles_and_revert(tmp_path):
    root = tmp_path / "vm"
    root.mkdir()
    (root / "swappiness").write_text("60\n")
    (root / "max_map_count").write_text("65530\n")
    (root / "drop_caches").write_text("0\n")

    memory = MemoryModule(root)
    extreme = {key: cmd for key, cmd, _label in memory.commands("extreme")}
    assert "10" in extreme["mem_swappiness"]
    assert "1048576" in extreme["mem_max_map"]

    assert memory.commands("eco") == []
    assert "sync" in memory.drop_caches_commands()[0][1]

    snapshot = memory.snapshot()
    revert = {key: cmd for key, cmd, _label
              in memory.revert_commands(snapshot)}
    assert "60" in revert["mem_swappiness"]
    assert "65530" in revert["mem_max_map"]


# ----------------------------------------------------------------------------
# Lote privilegiado y perfiles
# ----------------------------------------------------------------------------

def test_apply_commands_reports_each_result(monkeypatch):
    import cortex_engine.profiles.manager as module

    captured = {}

    def fake_run(cmd, timeout=0):
        captured["cmd"] = cmd
        return 0, "@@a:END 0\n@@b:END 1\n", ""

    monkeypatch.setattr(module, "run_privileged", fake_run)
    ok, failed = apply_commands([
        ("a", "true", "Aplicado"),
        ("b", "false", "Fallido"),
    ])
    assert ok == ["Aplicado"]
    assert failed and "Fallido" in failed[0]
    assert "bash" in captured["cmd"]
    # Un solo pkexec: un solo proceso bash.
    assert captured["cmd"][:2] == ["bash", "-c"]


def test_apply_commands_detects_cancellation(monkeypatch):
    import cortex_engine.profiles.manager as module

    monkeypatch.setattr(
        module, "run_privileged",
        lambda cmd, timeout=0: (126, "", "Not authorized"))
    ok, failed = apply_commands([("a", "true", "Aplicado")])
    assert not ok
    assert "cancelada" in failed[0].lower()


class _FakeModule:
    def __init__(self, commands, revert, snapshot):
        self._commands = commands
        self._revert = revert
        self._snapshot = snapshot

    def commands(self, key):
        return list(self._commands)

    def revert_commands(self, snapshot):
        return list(self._revert)

    def snapshot(self):
        return self._snapshot


def _manager(tmp_path, monkeypatch, ok=True):
    import cortex_engine.profiles.manager as module

    monkeypatch.setattr(
        module, "apply_commands",
        lambda commands, timeout=0: (
            ([label for _key, _cmd, label in commands], []) if ok
            else ([], ["falló"])))
    cpu = _FakeModule(
        [("cpu_governor", "true", "Governor aplicado")],
        [("cpu_governor", "true", "Governor restaurado")],
        {"governor": {"/x": "powersave"}})
    empty = _FakeModule([], [], {})
    config = CortexConfig(path=tmp_path / "cortex.json")
    activity = ActivityLog(path=tmp_path / "activity.log")
    store = RestoreStore(path=tmp_path / "restore.json")
    return ProfileManager(config, activity, cpu, empty, empty, store), config


def test_profile_manager_apply_and_revert(tmp_path, monkeypatch):
    manager, config = _manager(tmp_path, monkeypatch)
    ok, failed = manager.apply("extreme")
    assert ok == ["Governor aplicado"]
    assert not failed
    assert config.get("profile") == "extreme"
    assert manager.store.exists()
    assert "Perfil EXTREME aplicado" in (tmp_path / "activity.log").read_text()

    ok, failed = manager.revert()
    assert ok == ["Governor restaurado"]
    assert config.get("profile") == ""
    assert not manager.store.exists()


def test_profile_manager_keeps_snapshot_on_failure(tmp_path, monkeypatch):
    manager, config = _manager(tmp_path, monkeypatch, ok=False)
    ok, failed = manager.apply("eco")
    assert not ok and failed
    assert config.get("profile") == ""
    assert manager.store.exists()


def test_profile_manager_rejects_unknown_profile(tmp_path, monkeypatch):
    manager, _config = _manager(tmp_path, monkeypatch)
    ok, failed = manager.apply("turbo")
    assert not ok
    assert "desconocido" in failed[0]


def test_profile_manager_no_commands_keeps_snapshot_clean(tmp_path, monkeypatch):
    import cortex_engine.profiles.manager as module

    monkeypatch.setattr(
        module, "apply_commands", lambda commands, timeout=0: ([], []))
    empty = _FakeModule([], [], {})
    config = CortexConfig(path=tmp_path / "cortex.json")
    activity = ActivityLog(path=tmp_path / "activity.log")
    store = RestoreStore(path=tmp_path / "restore.json")
    manager = ProfileManager(config, activity, empty, empty, empty, store)
    ok, failed = manager.apply("balanced")
    assert not ok
    assert "no se ha cambiado nada" in failed[0]
    assert not store.exists()


# ----------------------------------------------------------------------------
# Game Booster y lanzador
# ----------------------------------------------------------------------------

def test_game_name_from_log():
    path = Path("Cyberpunk_2077_2026-11-19_20-00-00.csv")
    assert game_name_from_log(path) == "Cyberpunk_2077"


def test_booster_lifecycle(tmp_path):
    from cortex_engine.gaming.booster import GameBooster

    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "juego_2026-11-19_20-00-00.csv").write_text("fps\n60\n")
    booster = GameBooster(state_path=tmp_path / "booster.json", log_dir=logs)
    game = booster.active_game()
    assert game is not None
    assert game["name"] == "juego"


def test_booster_manual_process_selection(monkeypatch, tmp_path):
    from types import SimpleNamespace

    from cortex_engine.gaming import booster as booster_module
    from linux_optimizer.core import platform_info

    infos = [
        {"pid": 11, "name": "game.exe",
         "exe": r"D:\SteamLibrary\steamapps\common\Juego\game.exe",
         "nice": 8, "memory_info": SimpleNamespace(rss=1000)},
        {"pid": 22, "name": "tool.exe", "exe": r"C:\Tools\tool.exe",
         "nice": 8, "memory_info": SimpleNamespace(rss=100)},
    ]
    monkeypatch.setattr(platform_info, "IS_WINDOWS", True)
    monkeypatch.setattr(
        booster_module.psutil, "process_iter",
        lambda attrs: iter(SimpleNamespace(info=info) for info in infos))

    class FakeProcess:
        def __init__(self, pid):
            self.pid = pid

        def nice(self, value=None):
            return 8 if value is None else value

        def as_dict(self, attrs):
            return {"pid": self.pid, "name": "tool.exe", "nice": 8,
                    "memory_info": SimpleNamespace(rss=100)}

    monkeypatch.setattr(booster_module.psutil, "Process", FakeProcess)
    monkeypatch.setattr(booster_module.psutil, "pid_exists", lambda pid: True)
    booster = booster_module.GameBooster(state_path=tmp_path / "booster.json")

    listed = booster.list_processes()
    assert [item["pid"] for item in listed] == [11, 22]
    assert listed[0]["game_dir"] is True
    assert "PID 11" in listed[0]["label"]

    ok, message = booster.boost(22)
    assert ok and "prioridad alta" in message
    assert booster.boosted()["pid"] == 22


def test_cortex_launcher_opens_another_session(monkeypatch):
    from linux_optimizer.core import cortex_launcher

    assert cortex_launcher.app_root() is not None
    command = cortex_launcher.cortex_command()
    assert command is not None
    assert command[1:] == ["-m", "linux_optimizer", "--cortex"]

    started = {}

    class FakePopen:
        def __init__(self, cmd, **kwargs):
            started["cmd"] = cmd
            started["kwargs"] = kwargs

    monkeypatch.setattr(cortex_launcher.subprocess, "Popen", FakePopen)
    ok, message = cortex_launcher.launch_cortex()
    assert ok
    assert "abriendo" in message
    assert started["kwargs"]["start_new_session"] is True

    ok, message = cortex_launcher.launch_optimizer()
    assert ok
    assert started["cmd"][1:] == ["-m", "linux_optimizer"]


def test_app_entry_delegates_cortex_session(monkeypatch):
    called = {}

    def fake_cortex_main(argv):
        called["argv"] = argv
        return 0

    import cortex_engine.main as cortex_main_module

    monkeypatch.setattr(cortex_main_module, "main", fake_cortex_main)
    from linux_optimizer.app import main

    assert main(["--cortex"]) == 0
    assert called["argv"] == []


# ----------------------------------------------------------------------------
# Interfaz (offscreen)
# ----------------------------------------------------------------------------

@pytest.fixture(scope="module")
def app():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def test_cortex_window_has_independent_pages(app, tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    pytest.importorskip("PySide6")
    from cortex_engine.interface.theme import CORTEX_QSS
    from cortex_engine.interface.window import build_window

    window = build_window(CortexConfig(path=tmp_path / "cortex.json"))
    try:
        window.resize(1120, 720)
        window.show()
        app.processEvents()
        assert window.stack.count() == 8
        names = [type(page).__name__ for page in window.pages]
        assert names == [
            "PanelPage", "ProfilesPage", "CpuPage", "GpuPage",
            "MemoryPage", "BoosterPage", "ActivityPage", "SettingsPage",
        ]
        assert window._status_pill.text() == "SIN PERFIL"
        assert window.stack.currentIndex() == 0
        assert "Cortex" in window.windowTitle()
        assert window._optimizer_btn.text() == "Linux Optimizer"
        booster_page = next(page for page in window.pages
                            if type(page).__name__ == "BoosterPage")
        assert booster_page._process_combo is not None
        assert booster_page._manual_btn is not None
        assert "cortexSidebar" in CORTEX_QSS
        assert "cortexLaunch" in open(
            Path(__file__).resolve().parents[1] /
            "linux_optimizer/theme/style.qss", encoding="utf-8").read()
    finally:
        window.close()
        app.processEvents()


def test_main_window_has_single_cortex_access(app, tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    from linux_optimizer.main_window import MainWindow

    window = MainWindow()
    try:
        assert window._cortex_btn.text().endswith("Cortex Gaming Engine")
        assert window.stack.count() == len(window._pages)
    finally:
        window.monitor.stop()
        window.close()


def test_linux_desktop_integration_offers_cortex_session():
    root = Path(__file__).resolve().parents[1]
    desktop = (root / "packaging" / "linux-optimizer.desktop").read_text(
        encoding="utf-8")
    assert "Actions=Cortex;" in desktop
    assert "[Desktop Action Cortex]" in desktop
    action = desktop.split("[Desktop Action Cortex]", 1)[1]
    assert "Exec=@APPDIR@/run.sh --cortex" in action
    assert "Comment=" not in action  # clave no permitida en Desktop Action

    spec = (root / "packaging" / "linux-optimizer.spec").read_text(
        encoding="utf-8")
    assert "s|@APPDIR@/run.sh|%{_bindir}/linux-optimizer|g" in spec
    assert "Exec=.*run.sh" not in spec

    launcher = (root / "run.sh").read_text(encoding="utf-8")
    assert 'python3 -m linux_optimizer "$@"' in launcher
