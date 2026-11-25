"""Genera linux-optimizer.ico (Windows) a partir del SVG, sin dependencias.

Uso:  python packaging/windows/make_icon.py
"""

from __future__ import annotations

import struct
import sys
from pathlib import Path

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, Qt
from PySide6.QtGui import QImage, QPainter
from PySide6.QtSvg import QSvgRenderer

ROOT = Path(__file__).resolve().parents[2]
SVG_PATH = ROOT / "linux_optimizer" / "resources" / "linux-optimizer.svg"
ICO_PATH = ROOT / "linux_optimizer" / "resources" / "linux-optimizer.ico"
SIZES = (16, 24, 32, 48, 64, 128, 256)


def render_png(renderer: QSvgRenderer, size: int) -> bytes:
    image = QImage(size, size, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    renderer.render(painter)
    painter.end()

    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    if not image.save(buffer, "PNG"):
        raise RuntimeError("No se pudo convertir el SVG a PNG")
    data = bytes(buffer.data())
    buffer.close()
    return data


def build_ico(images: list[tuple[int, bytes]]) -> bytes:
    header = struct.pack("<HHH", 0, 1, len(images))
    offset = len(header) + 16 * len(images)
    entries = bytearray()
    payload = bytearray()
    for size, data in images:
        width = 0 if size >= 256 else size
        entries += struct.pack(
            "<BBBBHHII", width, width, 0, 0, 1, 32, len(data), offset)
        payload += data
        offset += len(data)
    return header + bytes(entries) + bytes(payload)


def main() -> int:
    if not SVG_PATH.exists():
        print(f"No se encontró {SVG_PATH}", file=sys.stderr)
        return 1
    renderer = QSvgRenderer(QByteArray(SVG_PATH.read_bytes()))
    if not renderer.isValid():
        print("El SVG no es válido", file=sys.stderr)
        return 1
    images = [(size, render_png(renderer, size)) for size in SIZES]
    ICO_PATH.write_bytes(build_ico(images))
    print(f"✔ Generado {ICO_PATH} ({ICO_PATH.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
