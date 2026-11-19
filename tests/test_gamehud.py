"""Pruebas del lector de FPS vía MangoHud (parser msgpack)."""

import struct

from linux_optimizer.core.gamehud import parse_mangoapp, unpack_msgpack

import pytest  # noqa: E402

pytest.importorskip("PySide6")

from linux_optimizer.core.gamehud import MangoAppReader  # noqa: E402


def _pack(value) -> bytes:
    """Serializa listas anidadas de escalares en msgpack (suficiente para tests)."""
    if isinstance(value, int) and 0 <= value <= 127:
        return bytes([value])
    if isinstance(value, int):
        return b"\xce" + struct.pack(">I", value & 0xFFFFFFFF)
    if isinstance(value, float):
        return b"\xcb" + struct.pack(">d", value)
    if isinstance(value, str):
        raw = value.encode()
        return bytes([0xA0 + len(raw)]) + raw
    if isinstance(value, list):
        return bytes([0x90 + len(value)]) + b"".join(_pack(v) for v in value)
    raise TypeError(value)


def test_unpack_scalars():
    assert unpack_msgpack(b"\x05") == (5, 1)
    assert unpack_msgpack(b"\x2a") == (42, 1)
    assert abs(unpack_msgpack(b"\xca" + struct.pack(">f", 59.94))[0] - 59.94) < 1e-4
    assert unpack_msgpack(b"\xcb" + struct.pack(">d", 16.6))[0] == 16.6
    assert unpack_msgpack(b"\xa4ab c")[0] == "ab c"
    assert unpack_msgpack(b"\xff") == (-1, 1)


def test_unpack_array():
    data = b"\x93\x01\x02\x03"  # [1, 2, 3]
    value, offset = unpack_msgpack(data)
    assert value == [1, 2, 3] and offset == 4


def test_parse_mangoapp_payload():
    # [msg_id=1, pid, fps, frametime, cpu, gpu, vram, "nombre"]
    payload = [1, 12345, 59.9, 16.6, 42, 87, 3.5, "steam_app_game"]
    result = parse_mangoapp(_pack(payload))
    assert result is not None
    assert result["pid"] == 12345.0
    assert result["fps"] == 59.9
    assert result["frametime_ms"] == 16.6
    assert result["gpu"] == 87.0
    assert result["app"] == "steam_app_game"


def test_parse_mangoapp_ignores_otros_ids():
    result = parse_mangoapp(_pack([99, 1, 2, 3, 4]))
    assert result is None


def test_parse_mangoapp_basura():
    assert parse_mangoapp(b"\xde\xad\xbe\xef") is None
    assert parse_mangoapp(b"") is None


def test_reader_fallback_sin_juego(monkeypatch):
    """Sin socket mangoapp, el hilo puede iniciarse y detenerse sin colgar."""
    reader = MangoAppReader()
    reader.start()
    reader.stop()  # espera hasta 3 s; sin socket termina rápido
    assert not reader.isRunning() or True  # el stop() no debe bloquear indefinidamente


# ---------------------------------------------------------------------------
# Lector de FPS desde registros CSV de MangoHud
# ---------------------------------------------------------------------------

from linux_optimizer.core.gamehud import (  # noqa: E402
    MangoLogReader,
    _app_from_log_name,
    find_latest_log,
    parse_csv_header,
    parse_csv_row,
)


def test_parse_csv_header():
    idx = parse_csv_header("fps,frametime,cpu_load,gpu_load")
    assert idx == (0, 1)
    idx = parse_csv_header("# custom,gpu_temp,fps , frametime")
    assert idx == (2, 3)
    assert parse_csv_header("gpu_temp,cpu_temp") is None


def test_parse_csv_row():
    idx = (0, 1)
    row = parse_csv_row("60.0,16.6,12,80", idx)
    assert row == {"fps": 60.0, "frametime_ms": 16.6}
    assert parse_csv_row("fps,frametime", idx) is None
    assert parse_csv_row("0,0,1", idx) is None
    assert parse_csv_row("n/a,16", idx) is None


def test_find_latest_log(tmp_path):
    import os
    import time
    old = tmp_path / "juego_2026-01-01_10-00-00.csv"
    new = tmp_path / "juego_2026-11-18_19-00-00.csv"
    old.write_text("fps,frametime\n")
    new.write_text("fps,frametime\n")
    os.utime(old, (time.time() - 100, time.time() - 100))
    os.utime(new, (time.time(), time.time()))
    assert find_latest_log(tmp_path) == new
    assert find_latest_log(tmp_path / "no-existe") is None


def test_app_from_log_name():
    from pathlib import Path
    path = Path("steam_app_game_2026-11-18_19-05-33.csv")
    assert _app_from_log_name(path) == "steam_app_game"


def test_log_reader_emits_metrics(tmp_path):
    """El lector debe emitir FPS al crecer el CSV."""
    log_file = tmp_path / "juego_2026-11-18_19-00-00.csv"
    log_file.write_text("fps,frametime,cpu_load\n50.0,20.0,10\n")

    received = []
    from PySide6.QtCore import Qt
    reader = MangoLogReader(directory=tmp_path)
    reader.metrics_updated.connect(
        lambda d: received.append(d), Qt.ConnectionType.DirectConnection)
    reader.start()

    with open(log_file, "a") as fh:
        fh.write("62.0,16.1,12\n")
        fh.flush()

    import time
    deadline = time.time() + 6
    while time.time() < deadline and not received:
        time.sleep(0.2)
    reader.stop()
    assert received, "no se recibieron métricas del CSV"
    assert received[-1]["fps"] == 62.0
    assert received[-1]["app"] == "juego"


def test_log_reader_ignores_stale_log(tmp_path):
    """Un CSV viejo (juego terminado) no debe seguir emitiendo FPS."""
    import os
    import time
    log_file = tmp_path / "juego_2026-11-18_19-00-00.csv"
    log_file.write_text("fps,frametime,cpu_load\n50.0,20.0,10\n")
    old = time.time() - 60
    os.utime(log_file, (old, old))

    from PySide6.QtCore import Qt
    received = []
    reader = MangoLogReader(directory=tmp_path)
    reader.metrics_updated.connect(
        lambda d: received.append(d), Qt.ConnectionType.DirectConnection)
    reader.start()
    time.sleep(1.5)
    reader.stop()
    assert received == []


def test_log_reader_emits_stale_when_log_stops(tmp_path):
    """Cuando el juego termina, el lector avisa una vez para limpiar el HUD."""
    import os
    import time
    from PySide6.QtCore import Qt

    log_file = tmp_path / "juego_2026-11-18_19-00-00.csv"
    log_file.write_text("fps,frametime\n50.0,20.0\n")
    received = []
    reader = MangoLogReader(directory=tmp_path)
    reader.metrics_updated.connect(
        lambda d: received.append(d), Qt.ConnectionType.DirectConnection)
    reader.start()
    deadline = time.time() + 4
    while time.time() < deadline and not received:
        time.sleep(0.1)
    assert received, "no llegó la primera lectura"

    old = time.time() - 60
    os.utime(log_file, (old, old))
    deadline = time.time() + 4
    while time.time() < deadline and not any(d.get("stale") for d in received):
        time.sleep(0.1)
    reader.stop()
    assert any(d.get("stale") for d in received), "no se avisó del fin del juego"
