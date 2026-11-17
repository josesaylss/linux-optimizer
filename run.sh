#!/usr/bin/env bash
# Linux Optimizer — lanzador (funciona desde el repo, el portable o el RPM)
set -euo pipefail
cd "$(dirname "$0")"

# 1) Entorno virtual local (repo / portable)
if [ -x ".venv/bin/python" ]; then
    exec .venv/bin/python -m linux_optimizer "$@"
fi

# 2) Paquete junto al lanzador (repo / portable / RPM instalado)
if [ -d "linux_optimizer" ]; then
    exec python3 -m linux_optimizer "$@"
fi

# 3) Instalación de sistema vía RPM (código en /usr/share)
if [ -d "/usr/share/linux-optimizer/linux_optimizer" ]; then
    cd /usr/share/linux-optimizer
    exec python3 -m linux_optimizer "$@"
fi

echo "No se encontró el paquete linux_optimizer." >&2
exit 1
