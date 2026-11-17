"""Pruebas de la ejecución por lotes (un solo diálogo de pkexec)."""

from linux_optimizer.core import cleaner


def test_parse_batch_output():
    out = "\n".join([
        "alguna salida del comando",
        "@@journal:BEGIN",
        "@@journal:END 0",
        "@@pkg_cache:BEGIN",
        "@@pkg_cache:END 1",
    ])
    parsed = cleaner._parse_batch_output(out)
    assert parsed == {"journal": 0, "pkg_cache": 1}


def test_build_batch_script():
    script = cleaner.build_batch_script([("a", "cmd_a"), ("b", "cmd_b")])
    lines = script.splitlines()
    assert lines[0] == "set +e"
    assert "echo '@@a:BEGIN'" in script
    assert "cmd_a" in script
    assert "echo '@@a:END' $?" in script
    assert "cmd_b" in script


def test_clean_batch_single_pkexec(monkeypatch, tmp_path):
    """Varias acciones root => exactamente UNA llamada a pkexec."""
    import pathlib
    home = pathlib.Path.home()
    (home / ".cache" / "batchtest").mkdir(parents=True, exist_ok=True)

    calls = {"pkexec": 0}

    def fake_privileged(cmd, timeout=600.0):
        calls["pkexec"] += 1
        # Devuelve salida con marcadores como lo haría el script real.
        return 0, "@@journal:END 0\n@@pkg_cache:END 0\n", ""

    monkeypatch.setattr(cleaner, "run_privileged", fake_privileged)
    targets = cleaner.build_targets("fedora")
    selected = [t for t in targets if t.key in ("journal", "pkg_cache")]
    assert all(t.needs_root for t in selected)

    results = cleaner.clean_batch(selected)
    assert calls["pkexec"] == 1
    assert results["journal"].error == ""
    assert results["pkg_cache"].error == ""
    assert "correctamente" in results["journal"].note


def test_clean_batch_user_targets_run_in_process(monkeypatch, tmp_path):
    """Los objetivos de usuario se ejecutan sin pkexec y con resultado real."""
    calls = {"pkexec": 0}

    def fake_privileged(cmd, timeout=600.0):
        calls["pkexec"] += 1
        return 0, "", ""

    monkeypatch.setattr(cleaner, "run_privileged", fake_privileged)
    trash = tmp_path / "trash" / "files"
    trash.mkdir(parents=True)
    (trash / "x.bin").write_bytes(b"0" * 32)

    def scan():
        return cleaner.ScanResult(size=32, files=1)

    def clean():
        return cleaner.CleanResult(freed=32, removed=1)

    target = cleaner.CleanTarget(
        key="trash", title="t", description="d", needs_root=False,
        scan=scan, clean=clean,
    )
    results = cleaner.clean_batch([target])
    assert calls["pkexec"] == 0
    assert results["trash"].freed == 32


def test_clean_batch_cancelled(monkeypatch):
    """Si el usuario cancela el diálogo, cada objetivo root reporta cancelación."""
    def fake_privileged(cmd, timeout=600.0):
        return 126, "", "Error executing command as another user: Request dismissed"

    monkeypatch.setattr(cleaner, "run_privileged", fake_privileged)
    targets = cleaner.build_targets("fedora")
    selected = [t for t in targets if t.needs_root]
    results = cleaner.clean_batch(selected)
    assert all("cancelada" in r.error for r in results.values())
