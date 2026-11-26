"""Entrada del modo Cortex Gaming Engine de la aplicación única.

Equivale a ``linux-optimizer --cortex``: abre la misma ventana de Linux
Optimizer directamente en modo Cortex, sin crear otro proceso.

    linux-optimizer --cortex
    python3 -m cortex_engine        (equivalente en desarrollo)
"""

from __future__ import annotations

import sys

from linux_optimizer.app import main as app_main


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv if argv is None else argv)
    args = [arg for arg in argv if arg != "--cortex"]
    return app_main(["--cortex", *args])


if __name__ == "__main__":
    raise SystemExit(main())
