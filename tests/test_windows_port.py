"""Pruebas del port de Windows: sesiones, rutas, perfiles y empaquetado.

Las funciones de Windows se prueban en Linux simulando la plataforma y
sustituyendo ``powercfg``/``psutil`` por dobles. Así se valida la lógica sin
tocar el sistema ni depender de una máquina Windows.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from cortex_engine.config import CortexConfig  # noqa: E402
from cortex_engine.cpu.windows import PLAN_GUIDS, active_plan, plan_commands  # noqa: E402
from linux_optimizer.core import platform_info  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


# ----------------------------------------------------------------------------
# Plataforma, distro y limpieza
# ----------------------------------------------------------------------------

def test_windows_distro_detection(monkeypatch):
    from linux_optimizer.core import distro

    monkeypatch.setattr(platform_info, "IS_WINDOWS", True)
    info = distro.detect_distro()
    assert info.name == "Windows"
    assert info.family == "windows"
    assert info.package_manager == "winget"
    assert info.is_supported


def test_windows_cleaner_targets(monkeypatch):
    from linux_optimizer.core import cleaner

    monkeypatch.setattr(platform_info, "IS_WINDOWS", True)
    targets = cleaner.build_windows_targets()
    assert [target.key for target in targets] == [
        "user_temp", "thumbnails", "trash"]
    assert all(target.available("windows") for target in targets)
    assert cleaner.build_targets("windows") == targets


def test_windows_hides_linux_only_pages(monkeypatch):
    from linux_optimizer import main_window

    monkeypatch.setattr(platform_info, "IS_WINDOWS", True)
    pages = main_window.pages_for_platform()
    names = {page.__name__ for _icon, _name, page in pages}
    assert "DashboardPage" in names
    assert "CleanerPage" in names
    assert "DiagnosticsPage" in names
    assert not names & {"GamingPage", "ServicesPage", "PowerPage"}


def test_windows_state_and_config_paths(monkeypatch, tmp_path):
    from cortex_engine import config as cortex_config
    from linux_optimizer import logging_utils

    monkeypatch.setattr(platform_info, "IS_WINDOWS", True)
    monkeypatch.setenv("APPDATA", str(tmp_path / "Roaming"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Local"))
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.delenv("XDG_STATE_HOME", raising=False)

    assert str(cortex_config.config_path()).startswith(str(tmp_path / "Roaming"))
    assert "cortex" in str(cortex_config.state_dir())
    assert str(logging_utils.state_dir()).startswith(str(tmp_path / "Local"))


# ----------------------------------------------------------------------------
# CPU, memoria y perfiles de Cortex en Windows
# ----------------------------------------------------------------------------

def test_windows_cpu_state_and_plan_commands(monkeypatch):
    from cortex_engine.cpu import windows_module

    monkeypatch.setattr(
        windows_module, "active_plan",
        lambda: {"guid": PLAN_GUIDS["balanced"], "name": "Equilibrado"})
    state = windows_module.WindowsCpuModule().state()
    assert state["governor"] == "Equilibrado"
    assert state["plan_guid"] == PLAN_GUIDS["balanced"]
    assert state["cpus"] >= 1

    commands = windows_module.WindowsCpuModule().commands("extreme")
    assert len(commands) == 1
    assert PLAN_GUIDS["extreme"] in commands[0][1]

    labels = [label for _key, _cmd, label in plan_commands("eco")]
    assert labels == ["Plan de energía «Ahorro de energía»"]


def test_windows_memory_has_no_unsafe_controls():
    from cortex_engine.memory.windows import WindowsMemoryModule

    memory = WindowsMemoryModule()
    assert memory.state() == {"swappiness": None, "max_map_count": None}
    assert memory.commands("extreme") == []
    assert memory.drop_caches_commands() == []


class FakeStore:
    def __init__(self):
        self.data = None

    def exists(self):
        return self.data is not None

    def save(self, snapshot):
        self.data = snapshot

    def load(self):
        return self.data

    def clear(self):
        self.data = None

    def info(self):
        return "instantánea de prueba"


class FakeActivity:
    def __init__(self):
        self.messages = []

    def log(self, message, level="INFO"):
        self.messages.append((level, message))


def _windows_manager(tmp_path, monkeypatch):
    from cortex_engine.profiles import windows as windows_profiles

    config = CortexConfig(path=tmp_path / "cortex.json")
    store = FakeStore()
    activity = FakeActivity()
    manager = windows_profiles.WindowsProfileManager(
        config, activity, store)
    return manager, config, store, activity, windows_profiles


def test_windows_profile_apply_and_restore(tmp_path, monkeypatch):
    manager, config, store, activity, module = _windows_manager(
        tmp_path, monkeypatch)
    applied = []

    monkeypatch.setattr(
        module, "active_plan",
        lambda: {"guid": PLAN_GUIDS["balanced"], "name": "Equilibrado"})
    monkeypatch.setattr(
        module, "set_plan",
        lambda guid: (applied.append(guid) or (True, "ok")))

    ok, failed = manager.apply("extreme")
    assert failed == []
    assert ok == ["Plan de energía «Alto rendimiento»"]
    assert applied == [PLAN_GUIDS["extreme"]]
    assert config.get("profile") == "extreme"
    assert store.data["windows"]["active_plan"] == PLAN_GUIDS["balanced"]
    assert any("Alto rendimiento" in message for _level, message in activity.messages)

    applied.clear()
    ok, failed = manager.revert()
    assert failed == []
    assert applied == [PLAN_GUIDS["balanced"]]
    assert config.get("profile") == ""
    assert not store.exists()


def test_windows_profile_refuses_without_current_plan(tmp_path, monkeypatch):
    manager, config, store, _activity, module = _windows_manager(
        tmp_path, monkeypatch)
    monkeypatch.setattr(
        module, "active_plan",
        lambda: {"guid": "", "name": "", "error": "sin powercfg"})
    monkeypatch.setattr(
        module, "set_plan",
        lambda _guid: pytest.fail("no debe cambiar el plan sin instantánea"))

    ok, failed = manager.apply("eco")
    assert ok == []
    assert failed and "no se ha cambiado nada" in failed[0]
    assert config.get("profile") == ""
    assert store.data is None


def test_windows_booster_detects_game_process(monkeypatch, tmp_path):
    from types import SimpleNamespace

    from cortex_engine.gaming import booster as booster_module

    monkeypatch.setattr(platform_info, "IS_WINDOWS", True)
    monkeypatch.setattr(booster_module, "_windows_visible_pids", lambda: {10, 20})
    processes = [
        {"pid": 10, "name": "explorer.exe", "exe": r"C:\Windows\explorer.exe",
         "nice": 8, "memory_info": SimpleNamespace(rss=100)},
        {"pid": 20, "name": "game.exe",
         "exe": r"D:\SteamLibrary\steamapps\common\Juego\game.exe",
         "nice": 8, "memory_info": SimpleNamespace(rss=1000)},
        {"pid": 30, "name": "background.exe",
         "exe": r"C:\Tools\background.exe",
         "nice": 8, "memory_info": SimpleNamespace(rss=5000)},
    ]
    monkeypatch.setattr(
        booster_module.psutil, "process_iter",
        lambda attrs: iter(SimpleNamespace(info=info) for info in processes))

    booster = booster_module.GameBooster(state_path=tmp_path / "booster.json")
    game = booster.active_game()
    assert game is not None
    assert game["name"] == "game.exe"
    process = booster.find_process()
    assert process is not None
    assert process["pid"] == 20
    assert process["game_dir"] is True


def test_windows_booster_boost_and_revert_use_priority(monkeypatch, tmp_path):
    from cortex_engine.gaming import booster as booster_module

    calls = []

    class FakeProcess:
        def __init__(self, pid):
            self.pid = pid

        def nice(self, value=None):
            if value is not None:
                calls.append(value)
            return 8 if value is None else value

    monkeypatch.setattr(platform_info, "IS_WINDOWS", True)
    monkeypatch.setattr(booster_module.psutil, "Process", FakeProcess)
    monkeypatch.setattr(booster_module.psutil, "pid_exists", lambda pid: True)

    booster = booster_module.GameBooster(state_path=tmp_path / "booster.json")
    monkeypatch.setattr(
        booster, "find_process",
        lambda: {"pid": 20, "name": "game.exe", "nice": 8})

    ok, message = booster.boost()
    assert ok and "prioridad alta" in message
    assert calls == [getattr(booster_module.psutil, "HIGH_PRIORITY_CLASS", 128)]
    saved = booster.boosted()
    assert saved is not None
    assert saved["platform"] == "windows"
    assert saved["old_nice"] == 8

    ok, message = booster.unboost()
    assert ok and "restaurada" in message
    assert calls[-1] == 8
    assert not booster.state_path.exists()


# ----------------------------------------------------------------------------
# Diagnóstico y launcher
# ----------------------------------------------------------------------------

def test_windows_diagnostics_checks(monkeypatch):
    from linux_optimizer.core import diagnostics

    monkeypatch.setattr(platform_info, "IS_WINDOWS", True)
    summary = diagnostics.check_system_summary()
    assert summary.severity == "ok"
    assert "Windows" in summary.detail

    monkeypatch.setattr(
        diagnostics, "run",
        lambda *args, **kwargs: (0, "Plan de energía actual: Equilibrado (381b4222-f694-41f0-9685-ff5bb260df2e)", ""))
    plan = diagnostics.check_power_plan()
    assert plan.severity == "ok"
    assert "Equilibrado" in plan.detail

    monkeypatch.setattr(
        diagnostics, "run", lambda *args, **kwargs: (127, "", "no disponible"))
    assert diagnostics.check_power_plan().severity == "info"


def test_launcher_uses_frozen_executable(monkeypatch):
    from linux_optimizer.core import cortex_launcher

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", r"C:\Apps\LinuxOptimizer.exe")
    assert cortex_launcher.cortex_command() == [
        r"C:\Apps\LinuxOptimizer.exe", "--cortex"]
    assert cortex_launcher.optimizer_command() == [
        r"C:\Apps\LinuxOptimizer.exe"]


def test_launcher_windows_detaches_session(monkeypatch):
    from linux_optimizer.core import cortex_launcher

    started = {}
    monkeypatch.setattr(platform_info, "IS_WINDOWS", True)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", r"C:\Apps\LinuxOptimizer.exe")
    monkeypatch.setattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x200,
                        raising=False)
    monkeypatch.setattr(subprocess, "DETACHED_PROCESS", 0x8, raising=False)
    monkeypatch.setattr(
        cortex_launcher.subprocess, "Popen",
        lambda cmd, **kwargs: started.update(cmd=cmd, kwargs=kwargs))
    monkeypatch.setattr(cortex_launcher, "cortex_available", lambda: True)

    ok, message = cortex_launcher.launch_cortex()
    assert ok and "otra sesión" in message
    assert started["cmd"] == [r"C:\Apps\LinuxOptimizer.exe", "--cortex"]
    assert started["kwargs"]["creationflags"] == 0x208
    assert "start_new_session" not in started["kwargs"]


# ----------------------------------------------------------------------------
# Empaquetado
# ----------------------------------------------------------------------------

def test_windows_packaging_files_exist():
    windows = ROOT / "packaging" / "windows"
    for name in (
        "linux_optimizer_win.py",
        "linux-optimizer.spec",
        "version_info.txt",
        "make_icon.py",
        "requirements-build.txt",
        "build-exe.ps1",
        "build-exe.bat",
        "README.md",
    ):
        assert (windows / name).is_file(), name

    spec = (windows / "linux-optimizer.spec").read_text(encoding="utf-8")
    compile(spec, "linux-optimizer.spec", "exec")
    assert "cortex_engine.main" in spec
    assert "theme.qss" in spec
    assert "console=False" in spec
    assert "linux-optimizer.ico" in spec

    version = (windows / "version_info.txt").read_text(encoding="utf-8")
    compile(version, "version_info.txt", "exec")
    assert "VSVersionInfo" in version
    assert "LinuxOptimizer.exe" in version


def test_windows_icon_is_valid():
    from linux_optimizer.resources import ICO_ICON_PATH

    data = ICO_ICON_PATH.read_bytes()
    assert data[:4] == b"\x00\x00\x01\x00"
    assert ICO_ICON_PATH.stat().st_size > 1000


def test_diagnostics_run_checks_windows(monkeypatch):
    from linux_optimizer.core import diagnostics

    monkeypatch.setattr(platform_info, "IS_WINDOWS", True)
    monkeypatch.setattr(diagnostics, "check_power_plan",
                        lambda: diagnostics.CheckResult("Plan", "ok", "ok"))
    monkeypatch.setattr(diagnostics, "check_disk_usage",
                        lambda: diagnostics.CheckResult("Disco", "ok", "ok"))
    monkeypatch.setattr(diagnostics, "check_memory",
                        lambda: diagnostics.CheckResult("RAM", "ok", "ok"))
    monkeypatch.setattr(diagnostics, "check_temperature",
                        lambda: diagnostics.CheckResult("Temp", "ok", "ok"))
    names = {check.name for check in diagnostics.run_checks()}
    assert names == {"Sistema", "Plan", "Disco", "RAM", "Temp"}
