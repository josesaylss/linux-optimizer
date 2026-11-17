"""Panel principal: CPU, RAM, GPU, temperatura, disco y red."""

from __future__ import annotations

import time

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from linux_optimizer.ui.widgets import (
    Card,
    SectionTitle,
    Sparkline,
    StatCard,
    fmt_rate,
)


def _fmt_uptime(secs: float) -> str:
    secs = int(secs)
    days, rem = divmod(secs, 86400)
    hours, rem = divmod(rem, 3600)
    minutes = rem // 60
    parts = []
    if days:
        parts.append(f"{days}d")
    parts.append(f"{hours}h {minutes}m")
    return " ".join(parts)


class DashboardPage(QWidget):
    """Panel de monitorización en vivo."""

    def __init__(self, monitor, distro_info, parent: QWidget | None = None):
        super().__init__(parent)
        self._monitor = monitor

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        outer.addWidget(scroll)

        content = QWidget()
        scroll.setWidget(content)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(4, 0, 4, 16)
        layout.setSpacing(14)

        # Cabecera
        self._summary = QLabel("")
        self._summary.setObjectName("headerSubtitle")
        layout.addWidget(self._summary)

        # Fila 1: CPU / RAM / GPU
        row1 = QHBoxLayout()
        row1.setSpacing(14)

        self.cpu_card = StatCard("CPU", show_bar=True)
        self.cpu_card.extra_label.setText("%")
        self.cpu_spark = Sparkline()
        self.cpu_card.body.addWidget(self.cpu_spark)
        row1.addWidget(self.cpu_card, 3)

        self.ram_card = StatCard("Memoria RAM", show_bar=True)
        row1.addWidget(self.ram_card, 3)

        self.gpu_card = StatCard("GPU")
        row1.addWidget(self.gpu_card, 3)
        layout.addLayout(row1)

        # Fila 2: temperatura / swap / red / disco IO
        row2 = QHBoxLayout()
        row2.setSpacing(14)
        self.temp_card = StatCard("Temperatura")
        row2.addWidget(self.temp_card, 1)
        self.swap_card = StatCard("Swap", show_bar=True)
        row2.addWidget(self.swap_card, 1)
        self.net_card = StatCard("Red")
        row2.addWidget(self.net_card, 1)
        self.io_card = StatCard("Disco I/O")
        row2.addWidget(self.io_card, 1)
        layout.addLayout(row2)

        # Discos
        disks_card = Card()
        disks_card.body.addWidget(SectionTitle("Almacenamiento"))
        self._disks_layout = QVBoxLayout()
        self._disks_layout.setSpacing(8)
        disks_card.body.addLayout(self._disks_layout)
        self._disk_rows: dict[str, tuple[QLabel, QProgressBar, QLabel]] = {}
        layout.addWidget(disks_card)

        # Detalle por núcleo
        cores_card = Card()
        cores_card.body.addWidget(SectionTitle("Uso por núcleo"))
        self._cores_grid = QGridLayout()
        self._cores_grid.setSpacing(8)
        cores_card.body.addLayout(self._cores_grid)
        self._core_rows: list[tuple[QLabel, QProgressBar]] = []
        layout.addWidget(cores_card)

        layout.addStretch(1)

        monitor.stats_updated.connect(self.update_stats)
        self._refresh_summary(distro_info)

    # ------------------------------------------------------------------

    def _refresh_summary(self, distro_info) -> None:
        cpu = self._monitor.cpu_info
        gpu_text = ", ".join(g.short() for g in self._monitor.gpus) or "GPU no detectada"
        self._summary.setText(
            f"{distro_info.pretty}  ·  {cpu.model} ({cpu.cores_physical}C/"
            f"{cpu.cores_logical}T)  ·  {gpu_text}"
        )

    # ------------------------------------------------------------------

    def update_stats(self, stats: dict) -> None:
        cpu = stats["cpu"]
        self.cpu_card.set_value(f"{cpu['percent']:.0f}%", cpu["model"])
        self.cpu_card.set_percent(cpu["percent"])
        self.cpu_spark.add_point(cpu["percent"])
        freq = cpu.get("freq_mhz") or 0
        if freq:
            self.cpu_card.extra_label.setText(f"{freq:,.0f} MHz")

        mem = stats["mem"]
        self.ram_card.set_value(
            f"{mem['percent']:.0f}%",
            f"{mem['used'] / 1024**3:.1f} GB usados de {mem['total'] / 1024**3:.1f} GB",
        )
        self.ram_card.set_percent(mem["percent"])

        # GPU: primer dispositivo con estadísticas en vivo (NVIDIA) o nombre.
        gpu_names = stats.get("gpu_names") or []
        gpu_stats = stats.get("gpus") or []
        if gpu_stats:
            g = gpu_stats[0]
            self.gpu_card.set_value(
                f"{g['util']:.0f}%",
                f"{g['name']}: {g['mem_used_mb']:.0f}/{g['mem_total_mb']:.0f} MB · {g['temp']:.0f} °C",
            )
            self.gpu_card.set_percent(g["util"])
        elif gpu_names:
            self.gpu_card.set_value("N/D", f"{gpu_names[0]} (uso disponible solo con NVIDIA)")
        else:
            self.gpu_card.set_value("N/D", "No se detectó GPU dedicada")

        temps = stats.get("temps") or []
        if temps:
            name, value = max(temps, key=lambda item: item[1])
            severity = "crítica" if value >= 90 else ("alta" if value >= 80 else "estable")
            self.temp_card.set_value(
                f"{value:.0f} °C", f"{severity} · {name.split('/')[-1]}"
            )
        else:
            self.temp_card.set_value("N/D", "Sin sensores disponibles")

        swap = stats["swap"]
        if swap["total"]:
            self.swap_card.set_value(
                f"{swap['percent']:.0f}%",
                f"{swap['used'] / 1024**3:.2f} GB de {swap['total'] / 1024**3:.1f} GB",
            )
            self.swap_card.set_percent(swap["percent"])
        else:
            self.swap_card.set_value("N/D", "Swap deshabilitado")

        net = stats["net_io"]
        self.net_card.set_value(
            f"↓ {fmt_rate(net['rx_bps'])}",
            f"↑ {fmt_rate(net['tx_bps'])}",
        )

        io = stats["disk_io"]
        self.io_card.set_value(
            f"L {fmt_rate(io['read_bps'])}",
            f"E {fmt_rate(io['write_bps'])}",
        )

        self._update_disks(stats["disks"])
        self._update_cores(cpu.get("per_core") or [])
        self._summary.setToolTip(f"Tiempo encendido: {_fmt_uptime(stats['uptime_secs'])}")

    # ------------------------------------------------------------------

    def _update_disks(self, disks: list[dict]) -> None:
        seen = set()
        for disk in disks:
            mount = disk["mount"]
            seen.add(mount)
            if mount not in self._disk_rows:
                name_label = QLabel(f"{mount}  ({disk['fstype']})")
                bar = QProgressBar()
                bar.setRange(0, 100)
                info_label = QLabel("")
                row = QHBoxLayout()
                row.addWidget(name_label, 2)
                row.addWidget(bar, 3)
                row.addWidget(info_label, 2)
                wrapper = QWidget()
                wrapper.setLayout(row)
                self._disks_layout.addWidget(wrapper)
                self._disk_rows[mount] = (name_label, bar, info_label)
            name_label, bar, info_label = self._disk_rows[mount]
            bar.setValue(int(disk["percent"]))
            info_label.setText(
                f"{disk['used'] / 1024**3:.1f} GB / {disk['total'] / 1024**3:.1f} GB"
            )
        # Quita filas de particiones que desaparecieron (ej. USB extraído).
        for mount in list(self._disk_rows):
            if mount not in seen:
                self._disk_rows.pop(mount)

    def _update_cores(self, per_core: list[float]) -> None:
        n = len(per_core)
        if not n:
            return
        # Crea filas la primera vez.
        if not self._core_rows:
            cols = 4
            for i in range(n):
                label = QLabel(f"Núcleo {i}")
                label.setStyleSheet("color:#8b95ad; font-size:11px;")
                bar = QProgressBar()
                bar.setRange(0, 100)
                box = QVBoxLayout()
                box.setSpacing(2)
                box.addWidget(label)
                box.addWidget(bar)
                cell = QWidget()
                cell.setLayout(box)
                self._cores_grid.addWidget(cell, i // cols, i % cols)
                self._core_rows.append((label, bar))
        for i, (label, bar) in enumerate(self._core_rows):
            if i < n:
                bar.setValue(int(per_core[i]))
