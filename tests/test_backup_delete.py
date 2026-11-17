"""Pruebas de eliminación de respaldos."""

from linux_optimizer.core.backup import BackupStore


def test_delete_snapshot(tmp_path):
    store = BackupStore(base_dir=tmp_path / "backups")
    snapshot_id = store.snapshot(kind="test", label="borrable")
    assert (store.base_dir / snapshot_id).is_dir()
    assert store.delete(snapshot_id)
    assert not (store.base_dir / snapshot_id).exists()
    assert store.list_snapshots() == []
    assert store.load(snapshot_id) is None


def test_delete_rejects_outside_base(tmp_path):
    store = BackupStore(base_dir=tmp_path / "backups")
    # Intento de path traversal: nunca debe borrar fuera del almacén.
    assert not store.delete("../etc")
    assert not store.delete("")
    assert not store.delete("/etc")
