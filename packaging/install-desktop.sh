#!/usr/bin/env bash
# Instala Linux Optimizer para el usuario actual (sin root):
#  - ícono en ~/.local/share/icons/hicolor/scalable/apps
#  - entrada de menú en ~/.local/share/applications
set -euo pipefail
cd "$(dirname "$0")/.."
APPDIR="$(pwd)"

ICON_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/icons/hicolor/scalable/apps"
APPS_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/applications"

install -Dm644 linux_optimizer/resources/linux-optimizer.svg "$ICON_DIR/linux-optimizer.svg"

sed "s|@APPDIR@|$APPDIR|g" packaging/linux-optimizer.desktop \
    > "$APPS_DIR/linux-optimizer.desktop"

chmod +x "$APPDIR/run.sh"

if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database "$APPS_DIR" 2>/dev/null || true
fi

echo "✔ Instalado. Busca «Linux Optimizer» en el menú de aplicaciones."
echo "  Menú: $APPS_DIR/linux-optimizer.desktop"
echo "  Ícono: $ICON_DIR/linux-optimizer.svg"
