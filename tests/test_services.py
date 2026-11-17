"""Pruebas de seguridad de servicios esenciales."""

from linux_optimizer.core import services


def test_essential_detection():
    assert services.is_essential("systemd-journald.service")
    assert services.is_essential("NetworkManager.service")
    assert services.is_essential("sddm.service")
    assert services.is_essential("dbus.service")
    assert not services.is_essential("cups.service")
    assert not services.is_essential("bluetooth.service")
    assert not services.is_essential("avahi-daemon.service")


def test_destructive_actions_blocked_on_essential():
    for unit in ("systemd-journald.service", "NetworkManager.service", "sddm.service"):
        assert not services.is_action_allowed(unit, "stop")
        assert not services.is_action_allowed(unit, "disable")
        # Lecturas y reinicios permitidos
        assert services.is_action_allowed(unit, "restart")
        assert services.is_action_allowed(unit, "start")
        assert services.is_action_allowed(unit, "enable")


def test_apply_action_refuses_without_execution(monkeypatch):
    """apply_action nunca debe llegar a ejecutar si la acción está bloqueada."""
    called = {"ran": False}

    def fake_privileged(cmd, timeout=120.0):
        called["ran"] = True
        return 0, "", ""

    monkeypatch.setattr(services, "run_privileged", fake_privileged)
    ok, message = services.apply_action(None, "NetworkManager.service", "stop")
    assert not ok
    assert not called["ran"]
    assert "esencial" in message.lower() or "esencial" in message


def test_action_blocked_reason():
    assert services.action_blocked_reason("cups.service", "stop") == ""
    assert "sddm.service" in services.action_blocked_reason("sddm.service", "stop")


def test_unknown_action_rejected():
    ok, message = services.apply_action(None, "cups.service", "mask")
    assert not ok
    assert "desconocida" in message.lower()
