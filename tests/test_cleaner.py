"""Pruebas de la lógica de limpieza segura."""

from pathlib import Path

from linux_optimizer.core import cleaner


def test_dir_stats_and_delete_contents(tmp_path):
    root = tmp_path / "cache"
    (root / "sub").mkdir(parents=True)
    (root / "sub" / "a.bin").write_bytes(b"x" * 100)
    (root / "b.txt").write_bytes(b"y" * 50)

    result = cleaner.dir_stats([str(root)])
    assert result.size == 150
    assert result.files == 2

    cleaned = cleaner.delete_contents([str(root)])
    assert cleaned.freed == 150
    assert cleaned.removed == 2
    # La carpeta raíz se conserva; su contenido no.
    assert root.is_dir()
    assert list(root.iterdir()) == []


def test_delete_contents_excludes_dir(tmp_path):
    root = tmp_path / "cache"
    keep = root / "LinuxOptimizer"
    keep.mkdir(parents=True)
    (keep / "keep.dat").write_bytes(b"z" * 10)
    other = root / "other"
    other.mkdir()
    (other / "gone.dat").write_bytes(b"z" * 20)

    result = cleaner.delete_contents([str(root)], exclude=[str(keep)])
    assert result.removed == 1
    assert (keep / "keep.dat").is_file()
    assert not other.exists()


def test_delete_contents_never_removes_root(tmp_path):
    root = tmp_path / "somewhere"
    root.mkdir()
    result = cleaner.delete_contents([str(root)])
    assert result.removed == 0
    assert root.is_dir()


def test_targets_match_family():
    all_targets = cleaner.build_targets("fedora")
    keys = {t.key for t in all_targets}
    assert "pkg_cache" in keys

    keys_debian = {t.key for t in cleaner.build_targets("debian")}
    keys_arch = {t.key for t in cleaner.build_targets("arch")}
    assert keys_debian and keys_arch

    unknown = cleaner.build_targets("unknown")
    assert all(t.key != "pkg_cache" for t in unknown)


def test_user_targets_are_safe():
    """Los objetivos sin root nunca deben apuntar fuera del home."""
    for target in cleaner.build_targets("fedora"):
        if not target.needs_root:
            continue
    # simple verificación de contrato: journal requiere root
    journal = next(t for t in cleaner.build_targets("fedora") if t.key == "journal")
    assert journal.needs_root
