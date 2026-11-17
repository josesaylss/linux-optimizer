"""Pruebas de ajustes de kernel (swappiness)."""

from linux_optimizer.core import kernel
from linux_optimizer.core.backup import BackupStore


def test_validate():
    assert kernel.validate_swappiness(10) == ""
    assert kernel.validate_swappiness(0) == ""
    assert kernel.validate_swappiness(100) == ""
    assert kernel.validate_swappiness(-1)
    assert kernel.validate_swappiness(101)
    assert kernel.validate_swappiness("10")  # type: ignore[arg-type]


def test_conf_script_content():
    script = kernel._write_conf_script(10)
    assert "vm.swappiness = 10" in script
    assert kernel.SYSCTL_CONF in script
    assert "mkdir -p /etc/sysctl.d" in script


def test_current_swappiness_readable():
    value = kernel.current_swappiness()
    assert isinstance(value, int)
    assert 0 <= value <= 100


def test_snapshot_created_before_apply(monkeypatch, tmp_path):
    """apply_swappiness siempre crea un snapshot antes de ejecutar."""
    store = BackupStore(base_dir=tmp_path / "backups")
    executed = {"commands": []}

    def fake_privileged(cmd, timeout=30.0):
        executed["commands"].append(cmd)
        return 0, "", ""

    monkeypatch.setattr(kernel, "run_privileged", fake_privileged)
    ok, message = kernel.apply_swappiness(10, store, persist=False)
    assert ok
    # Primero snapshot, luego el comando de /proc.
    assert len(store.list_snapshots(kind="kernel")) == 1
    assert store.latest("kernel")["data"]["swappiness"] == kernel.current_swappiness()
    assert len(executed["commands"]) == 1
    assert "/proc/sys/vm/swappiness" in executed["commands"][0][2]
    assert message == f"vm.swappiness = 10 (aplicado en tiempo de ejecución)"


def test_apply_rejects_invalid_without_executing(monkeypatch, tmp_path):
    store = BackupStore(base_dir=tmp_path / "backups")
    executed = {"ran": False}

    def fake_privileged(cmd, timeout=30.0):
        executed["ran"] = True
        return 0, "", ""

    monkeypatch.setattr(kernel, "run_privileged", fake_privileged)
    ok, _message = kernel.apply_swappiness(150, store, persist=False)
    assert not ok
    assert not executed["ran"]
    assert not store.list_snapshots()
