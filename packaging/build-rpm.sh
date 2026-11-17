#!/usr/bin/env bash
# Construye el RPM de Linux Optimizer en un directorio de build local.
# Requiere: sudo dnf install -y rpm-build
set -euo pipefail
cd "$(dirname "$0")"

if ! command -v rpmbuild >/dev/null 2>&1; then
    echo "✖ Falta rpmbuild. Instálalo con:"
    echo "    sudo dnf install -y rpm-build"
    exit 1
fi

VERSION="0.1.0"
NAME="linux-optimizer"
TOPDIR="${TOPDIR:-$PWD/rpm/build}"
mkdir -p "$TOPDIR"/{BUILD,RPMS,SOURCES,SPECS,SRPMS}

# Tarball: regenerarlo desde git para garantizar contenido actualizado.
echo "→ Generando tarball fuente $NAME-$VERSION.tar.gz…"
git ls-files | grep -v -E '^(packaging/rpm|\.venv)' \
    | tar --transform "s,^,$NAME-$VERSION/," -czf "$TOPDIR/SOURCES/$NAME-$VERSION.tar.gz" -T -

cp "$NAME.spec" "$TOPDIR/SPECS/"

echo "→ Compilando RPM (noarch, binario)…"
rpmbuild -bb \
    --define "_topdir $TOPDIR" \
    --quiet \
    "$TOPDIR/SPECS/$NAME.spec"

echo
echo "✔ RPM generado:"
ls -lh "$TOPDIR/RPMS/noarch/"
echo "  Instalar con:  sudo dnf install $TOPDIR/RPMS/noarch/$NAME-$VERSION-*.noarch.rpm"
