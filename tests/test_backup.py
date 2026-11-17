"""Pruebas del almacén de respaldos."""

from linux_optimizer.core.backup import BackupStore


def test_snapshot_and_restore(tmp_path):
    src = tmp_path / "orig.conf"
    src.write_text("valor=1\n", encoding="utf-8")
    store = BackupStore(base_dir=tmp_path / "backups")

    snapshot_id = store.snapshot(
        kind="test", label="prueba", data={"clave": "valor"}, file_paths=[str(src)],
    )
    assert snapshot_id
    assert (store.base_dir / snapshot_id / "metadata.json").is_file()

    # Modificar el original y restaurar.
    src.write_text("valor=roto\n", encoding="utf-8")
    restored = store.restore_files(snapshot_id)
    assert restored == [str(src)]
    assert src.read_text(encoding="utf-8") == "valor=1\n"


def test_list_and_latest(tmp_path):
    store = BackupStore(base_dir=tmp_path / "backups")
    store.snapshot(kind="services", label="a")
    store.snapshot(kind="power", label="b")
    assert len(store.list_snapshots()) == 2
    assert len(store.list_snapshots(kind="power")) == 1
    assert store.latest("power")["label"] == "b"
    assert store.latest("services")["label"] == "a"
    assert store.latest("no-existe") is None


def test_load_missing(tmp_path):
    store = BackupStore(base_dir=tmp_path / "backups")
    assert store.load("inexistente") is None
    assert store.restore_files("inexistente") == []
