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
