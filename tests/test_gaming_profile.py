"""Pruebas del perfil automático de Modo Gaming (estilo GeForce Experience)."""

from linux_optimizer.core.backup import BackupStore
from linux_optimizer.core.gaming import GamingAction, GamingManager, _cpu_vendor


def make_manager(tmp_path) -> GamingManager:
    return GamingManager(BackupStore(base_dir=tmp_path / "backups"))


def test_recommended_keys_filters_supported_pending(tmp_path):
    manager = make_manager(tmp_path)
    manager.actions = [
        GamingAction(key="a", title="A", description="", needs_root=False,
                     recommended=True, supported=True),
        GamingAction(key="b", title="B", description="", needs_root=False,
                     recommended=False, supported=True),
        GamingAction(key="c", title="C", description="", needs_root=False,
                     recommended=True, supported=False),
        GamingAction(key="d", title="D", description="", needs_root=False,
                     recommended=True, supported=True, applied=True),
    ]
    assert manager.recommended_keys() == ["a"]


def test_recommended_never_includes_background_services(tmp_path):
    manager = make_manager(tmp_path)
    keys = set(manager.recommended_keys())
    assert not keys & {
        "clean_cache", "drop_caches",
        "stop_bluetooth", "stop_cups", "stop_avahi",
    }
    by_key = {action.key: action for action in manager.actions}
    for key in keys:
        assert by_key[key].supported
        assert by_key[key].recommended


def test_auto_profile_notes_cover_every_recommended_action(tmp_path):
    manager = make_manager(tmp_path)
    usable, skipped = manager.auto_profile_notes()
    recommended = [a for a in manager.actions if a.recommended]
    assert len(usable) + len(skipped) == len(recommended)
    assert all(":" in line for line in skipped)


def test_auto_profile_label_mentions_cpu_and_gpu(tmp_path):
    label = make_manager(tmp_path).auto_profile_label()
    assert label.startswith("CPU ")
    assert "GPU " in label


def test_cpu_vendor_detection():
    assert _cpu_vendor(
        "AMD Ryzen 5 3450U with Radeon Vega Mobile Gfx") == "AMD"
    assert _cpu_vendor("12th Gen Intel(R) Core(TM) i7-1260P") == "Intel"
    assert _cpu_vendor("") == "detectada"
