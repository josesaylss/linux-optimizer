#!/usr/bin/env bash
# Genera un paquete portable de Linux Optimizer para instalar en otra PC:
#   packaging/portable/linux-optimizer-0.1.0-portable.tar.gz
#
# La PC destino solo necesita: python3 (>=3.10), pip y un entorno gráfico.
set -euo pipefail
cd "$(dirname "$0")/.."
VERSION="0.1.0"
NAME="linux-optimizer-$VERSION-portable"
OUT_DIR="packaging/portable"
mkdir -p "$OUT_DIR"

STAGE=$(mktemp -d)
trap 'rm -rf "$STAGE"' EXIT
STAGE_NAME="$STAGE/$NAME"
mkdir -p "$STAGE_NAME"

# Código del paquete + lanzador + instalador de menú.
cp -a linux_optimizer "$STAGE_NAME/"
cp run.sh "$STAGE_NAME/"
cp packaging/install-desktop.sh "$STAGE_NAME/install-menu.sh"
cp requirements.txt "$STAGE_NAME/"
find "$STAGE_NAME" -name '__pycache__' -type d -exec rm -rf {} + 2>/dev/null || true

tar -czf "$OUT_DIR/$NAME.tar.gz" -C "$STAGE" "$NAME"

echo "✔ Paquete portable creado: $OUT_DIR/$NAME.tar.gz"
echo "  Cópialo a la otra PC y sigue el archivo INSTALAR.txt (lo genero aparte)."
