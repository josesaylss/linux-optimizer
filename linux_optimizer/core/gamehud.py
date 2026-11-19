"""Lector de FPS en vivo vía MangoHud (socket /tmp/mangoapp).

Cuando un juego corre con MangoHud, la librería crea el socket
/tmp/mangoapp (Unix SEQPACKET) y publica métricas en msgpack:
[msg_id=1, pid, fps, frametime_ms, cpu, gpu, vram_mb, ...].

Este módulo implementa un parser msgpack mínimo (sin dependencias
externas) y un hilo que reconecta automáticamente mientras el HUD está
abierto. Si no hay juego con MangoHud, simplemente no recibe datos.
"""

from __future__ import annotations

import logging
import os
import socket
import struct
import time
from pathlib import Path

from PySide6.QtCore import QThread, Signal

MANGOAPP_SOCKET = "/tmp/mangoapp"
log = logging.getLogger("LinuxOptimizer.fps")


# ----------------------------------------------------------------------------
# Parser msgpack mínimo (arrays/escalares: suficiente para mangoapp)
# ----------------------------------------------------------------------------

def unpack_msgpack(data: bytes, offset: int = 0) -> tuple[object, int]:
    if offset >= len(data):
        raise ValueError("fin de datos inesperado")
    b = data[offset]
    if b <= 0x7F:
        return b, offset + 1
    if b >= 0xE0:  # negative fixint
        return b - 0x100, offset + 1
    if 0x80 <= b <= 0x8F:  # fixmap
        n = b - 0x80
        offset += 1
        result: dict = {}
        for _ in range(n):
            key, offset = unpack_msgpack(data, offset)
            value, offset = unpack_msgpack(data, offset)
            result[key] = value
        return result, offset
    if 0x90 <= b <= 0x9F:  # fixarray
        n = b - 0x90
        offset += 1
        arr = []
        for _ in range(n):
            value, offset = unpack_msgpack(data, offset)
            arr.append(value)
        return arr, offset
    if 0xA0 <= b <= 0xBF:  # fixstr
        n = b - 0xA0
        return data[offset + 1:offset + 1 + n].decode("utf-8", "replace"), offset + 1 + n
    if b == 0xC0:
        return None, offset + 1
    if b == 0xC2:
        return False, offset + 1
    if b == 0xC3:
        return True, offset + 1
    if b == 0xCA:  # float32
        return struct.unpack_from(">f", data, offset + 1)[0], offset + 5
    if b == 0xCB:  # float64
        return struct.unpack_from(">d", data, offset + 1)[0], offset + 9
    if b == 0xCC:  # uint8
        return data[offset + 1], offset + 2
    if b == 0xCD:  # uint16
        return int.from_bytes(data[offset + 1:offset + 3], "big"), offset + 3
    if b == 0xCE:  # uint32
        return int.from_bytes(data[offset + 1:offset + 5], "big"), offset + 5
    if b == 0xD0:  # int8
        return struct.unpack_from(">b", data, offset + 1)[0], offset + 2
    if b == 0xD1:  # int16
        return struct.unpack_from(">h", data, offset + 1)[0], offset + 3
    if b == 0xD2:  # int32
        return struct.unpack_from(">i", data, offset + 1)[0], offset + 5
    if b == 0xD9:  # str8
        n = data[offset + 1]
        return data[offset + 2:offset + 2 + n].decode("utf-8", "replace"), offset + 2 + n
    if b == 0xDC:  # array16
        n = int.from_bytes(data[offset + 1:offset + 3], "big")
        offset += 3
        arr = []
        for _ in range(n):
            value, offset = unpack_msgpack(data, offset)
            arr.append(value)
        return arr, offset
    if b == 0xDD:  # array32
        n = int.from_bytes(data[offset + 1:offset + 5], "big")
        offset += 5
        arr = []
        for _ in range(n):
            value, offset = unpack_msgpack(data, offset)
            arr.append(value)
        return arr, offset
    raise ValueError(f"tipo msgpack no soportado: 0x{b:02x}")


def _num(value, default: float | None = None) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return default


def _proc_name(pid: float | None) -> str:
    if not pid:
        return ""
    try:
        with open(f"/proc/{int(pid)}/comm", encoding="utf-8") as fh:
            return fh.read().strip()
    except (OSError, ValueError):
        return ""


def parse_mangoapp(data: bytes) -> dict | None:
    """Convierte un datagrama de mangoapp en métricas legibles."""
    try:
        value, _offset = unpack_msgpack(data)
    except (ValueError, IndexError, struct.error):
        return None
    if not isinstance(value, list) or len(value) < 4:
        return None
    msg_id = _num(value[0])
    if msg_id != 1:
        return None
    payload = {
        "pid": _num(value[1]),
        "fps": _num(value[2]),
        "frametime_ms": _num(value[3]),
        "cpu": _num(value[4]),
        "gpu": _num(value[5]),
        "vram_mb": _num(value[6]),
    }
    for element in value[6:]:
        if isinstance(element, str):
            payload["app"] = element
            break
    if not payload.get("app"):
        payload["app"] = _proc_name(payload.get("pid"))
    return payload


# ----------------------------------------------------------------------------
# Hilo lector del socket
# ----------------------------------------------------------------------------

class MangoAppReader(QThread):
    """Lee métricas del juego desde /tmp/mangoapp mientras esté disponible."""

    metrics_updated = Signal(dict)

    RECONNECT_SECS = 3.0
    RECV_TIMEOUT = 2.0

    def __init__(self, parent=None):
        super().__init__(parent)
        self._running = False

    def run(self) -> None:  # pragma: no cover - hilo
        self._running = True
        sock: socket.socket | None = None
        while self._running:
            try:
                if sock is None:
                    if not os.path.exists(MANGOAPP_SOCKET):
                        time.sleep(self.RECONNECT_SECS)
                        continue
                    sock = socket.socket(socket.AF_UNIX, socket.SOCK_SEQPACKET)
                    sock.settimeout(self.RECV_TIMEOUT)
                    sock.connect(MANGOAPP_SOCKET)
                data = sock.recv(4096)
                if not data:
                    raise ConnectionError("socket cerrado por el juego")
                payload = parse_mangoapp(data)
                if payload:
                    self.metrics_updated.emit(payload)
            except (ConnectionError, OSError, socket.timeout):
                # El juego cerró el socket o aún no existe: reintentar.
                try:
                    if sock is not None:
                        sock.close()
                except OSError:
                    pass
                sock = None
                if self._running:
                    time.sleep(self.RECONNECT_SECS)

    def stop(self) -> None:
        self._running = False
        # recv con timeout 2 s garantiza la salida del hilo pronto.
        self.wait(3000)

    def request_stop(self) -> None:
        """Pide al hilo que termine sin bloquear el hilo de la interfaz."""
        self._running = False


# ----------------------------------------------------------------------------
# FPS desde los registros CSV de MangoHud (funciona con `mangohud %command%`)
# ----------------------------------------------------------------------------

MANGO_LOG_DIR = Path.home() / ".local/state/LinuxOptimizer/mangohud-logs"


def ensure_mangolog_dir() -> Path:
    """Crea la carpeta donde MangoHud escribirá sus registros CSV."""
    MANGO_LOG_DIR.mkdir(parents=True, exist_ok=True)
    return MANGO_LOG_DIR


def find_latest_log(directory: Path = MANGO_LOG_DIR) -> Path | None:
    """Devuelve el CSV de MangoHud más reciente, o None."""
    try:
        files = [p for p in directory.glob("*.csv") if p.is_file()]
    except OSError:
        return None
    if not files:
        return None
    return max(files, key=lambda p: p.stat().st_mtime)


def parse_csv_header(line: str) -> tuple[int, int] | None:
    """Detecta las columnas fps y frametime en la cabecera CSV de MangoHud."""
    cleaned = line.strip().lstrip("#").strip()
    if not cleaned:
        return None
    columns = [c.strip().lower() for c in cleaned.split(",")]
    try:
        return columns.index("fps"), columns.index("frametime")
    except ValueError:
        return None


def parse_csv_row(line: str, indices: tuple[int, int]) -> dict | None:
    """Convierte una fila de datos del CSV en métricas legibles."""
    fps_idx, ft_idx = indices
    fields = line.strip().split(",")
    if len(fields) <= max(indices):
        return None
    try:
        fps = float(fields[fps_idx])
        frametime = float(fields[ft_idx])
    except (ValueError, IndexError):
        return None
    if fps <= 0:
        return None
    return {"fps": fps, "frametime_ms": frametime}


def _app_from_log_name(path: Path) -> str:
    """Extrae el nombre del juego del nombre de archivo del registro."""
    stem = path.stem
    # Formato típico: "<juego>_2026-11-18_19-05-33"
    parts = stem.rsplit("_", 2)
    return parts[0] if len(parts) == 3 else stem


class MangoLogReader(QThread):
    """Lee el último CSV de MangoHud y emite los FPS en tiempo real."""

    metrics_updated = Signal(dict)

    POLL_SECS = 0.5
    # Un registro activo crece muy rápido (~60 líneas/s). Leer sin límite en
    # un bucle puede acaparar el GIL y congelar la interfaz, así que cada
    # pasada procesa como máximo este número de líneas.
    MAX_LINES_PER_PASS = 400
    # Si el CSV lleva este tiempo sin cambios, el juego ya terminó: no se
    # siguen emitiendo FPS viejos.
    STALE_SECS = 5.0
    # Al abrir un registro largo se salta hasta el final (solo interesa el
    # último dato) leyendo como mucho este tramo.
    TAIL_BYTES = 64 * 1024

    def __init__(self, directory: Path = MANGO_LOG_DIR, parent=None):
        super().__init__(parent)
        self._dir = directory
        self._running = False

    def run(self) -> None:  # pragma: no cover - hilo
        self._running = True
        fh = None
        current: str | None = None
        indices: tuple[int, int] | None = None
        was_fresh = False
        while self._running:
            latest = find_latest_log(self._dir)
            if latest is None:
                if fh is not None:
                    fh.close()
                    fh = None
                    current = None
                    indices = None
                if was_fresh:
                    self.metrics_updated.emit({"stale": True})
                    was_fresh = False
                time.sleep(self.POLL_SECS)
                continue
            if str(latest) != current:
                if fh is not None:
                    fh.close()
                try:
                    fh = open(latest, encoding="utf-8", errors="replace")
                except OSError:
                    fh = None
                    time.sleep(self.POLL_SECS)
                    continue
                current = str(latest)
                indices = None
                log.info("FPS: analizando registro %s", latest.name)
                # Busca la cabecera entre las primeras líneas.
                for _ in range(12):
                    line = fh.readline()
                    if not line:
                        break
                    found = parse_csv_header(line)
                    if found:
                        indices = found
                        break
                if indices is None:
                    log.warning("FPS: %s no tiene cabecera fps,frametime", latest.name)
                else:
                    # Salta al final: no hace falta recorrer todo el archivo.
                    try:
                        size = os.fstat(fh.fileno()).st_size
                        fh.seek(max(fh.tell(), size - self.TAIL_BYTES))
                    except OSError:
                        pass
            if fh is None or indices is None:
                time.sleep(self.POLL_SECS)
                continue
            last: dict | None = None
            for _ in range(self.MAX_LINES_PER_PASS):
                line = fh.readline()
                if not line:
                    break
                parsed = parse_csv_row(line, indices)
                if parsed:
                    last = parsed
            fresh = False
            try:
                fresh = (time.time() - latest.stat().st_mtime) < self.STALE_SECS
            except OSError:
                fresh = False
            if last and fresh:
                last["app"] = _app_from_log_name(latest)
                self.metrics_updated.emit(last)
                was_fresh = True
            elif was_fresh:
                # El juego terminó (el registro dejó de crecer): se avisa una
                # sola vez para que el HUD limpie los FPS en vez de congelarlos.
                self.metrics_updated.emit({"stale": True})
                was_fresh = False
            time.sleep(self.POLL_SECS)
        if fh is not None:
            fh.close()

    def stop(self) -> None:
        self._running = False
        self.wait(3000)

    def request_stop(self) -> None:
        """Pide al hilo que termine sin bloquear el hilo de la interfaz."""
        self._running = False
