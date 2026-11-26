"""Punto de entrada del ejecutable de Windows.

Es el mismo ejecutable y la misma ventana para los dos modos:

    LinuxOptimizer.exe             → Linux Optimizer
    LinuxOptimizer.exe --cortex    → Cortex Gaming Engine

PyInstaller usa este archivo como script principal del .exe.
"""

from __future__ import annotations

import multiprocessing
import sys

from linux_optimizer.app import main

if __name__ == "__main__":
    multiprocessing.freeze_support()
    raise SystemExit(main(sys.argv))
