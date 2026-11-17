#!/usr/bin/env bash
# Linux Optimizer — lanzador
set -euo pipefail
cd "$(dirname "$0")"

if [ -x ".venv/bin/python" ]; then
    exec .venv/bin/python -m linux_optimizer "$@"
fi
exec python3 -m linux_optimizer "$@"
