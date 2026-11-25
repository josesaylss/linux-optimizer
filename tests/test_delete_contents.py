"""Pruebas de delete_contents: omitidos por permisos vs error real."""

import os

import pytest

from linux_optimizer.core.cleaner import delete_contents


@pytest.fixture
def cache_dir(tmp_path):
    return tmp_path / "cache"


def test_borra_contenido_normal(cache_dir):
    cache_dir.mkdir()
    (cache_dir / "a.bin").write_bytes(b"x" * 100)
    sub = cache_dir / "sub"
    sub.mkdir()
    (sub / "b.bin").write_bytes(b"y" * 50)
    res = delete_contents([str(cache_dir)])
    assert res.error == ""
    assert res.note == ""
    assert res.removed == 2
    assert res.freed == 150
    assert cache_dir.exists() and not any(cache_dir.iterdir())


def test_permisos_suficientes_sin_borrar_nada_reporta_error(cache_dir):
    """Si NADA se puede borrar, sí es un error."""
    cache_dir.mkdir()
    locked = cache_dir / "locked"
    locked.mkdir()
    (locked / "inner.bin").write_bytes(b"z" * 50)
    os.chmod(locked, 0o000)
    try:
        res = delete_contents([str(cache_dir)])
        assert res.removed == 0
        # El texto del sistema depende de la locale («Permission denied»,
        # «Permiso denegado»…): basta con que se reporte el error real.
        assert res.error
        assert "locked" in res.error
        assert res.note == ""
    finally:
        os.chmod(locked, 0o700)


def test_permisos_parciales_cuenta_omitidos_sin_error(cache_dir):
    """Si algo se borró y algo no (permisos), es nota, no error."""
    cache_dir.mkdir()
    (cache_dir / "a.bin").write_bytes(b"x" * 100)
    locked = cache_dir / "locked"
    locked.mkdir()
    (locked / "inner.bin").write_bytes(b"z" * 50)
    os.chmod(locked, 0o000)
    try:
        res = delete_contents([str(cache_dir)])
        assert res.error == ""
        assert res.removed == 1
        assert res.freed == 100
        assert "omitidos" in res.note
        assert "1" in res.note
    finally:
        os.chmod(locked, 0o700)


def test_exclude_no_borra_lo_excluido(cache_dir, tmp_path):
    cache_dir.mkdir()
    app = cache_dir / "LinuxOptimizer"
    app.mkdir()
    (app / "log.txt").write_text("hola")
    res = delete_contents([str(cache_dir)], exclude=[str(app)])
    assert res.removed == 0
    assert (app / "log.txt").exists()


def test_ruta_inexistente_no_falla():
    res = delete_contents(["/tmp/opencode/esta-ruta-no-existe-xyz"])
    assert res.error == ""
    assert res.removed == 0
