# Spec para construir un RPM de Linux Optimizer en Fedora.
#
#   rpmbuild -bb packaging/linux-optimizer.spec
#   (el tarball se toma de ~/.cache o se define con --define "_sourcedir $PWD")
#
# Nota: usa PySide6/psutil del sistema (python3-pyside6, python3-psutil).

Name:           linux-optimizer
Version:        0.1.0
Release:        1%{?dist}
Summary:        Herramienta gráfica para optimizar el rendimiento de Linux
License:        MIT
URL:            https://example.invalid/linux-optimizer
Source0:        %{name}-%{version}.tar.gz

BuildArch:      noarch
Requires:       python3-pyside6
Requires:       python3-psutil
Requires:       polkit
Requires:       hicolor-icon-theme

%description
Linux Optimizer es una aplicación gráfica (PySide6) para monitorear y optimizar
el rendimiento de Linux: panel de CPU/RAM/GPU/temperatura/disco, limpieza segura
de cachés, modo gaming, administración de servicios systemd, perfiles de energía
y diagnóstico. Pensada para Fedora y arquitectura lista para Debian/Ubuntu/Arch.

%prep
%setup -q -n %{name}-%{version}

%build
# No requiere compilación.

%install
# Localiza el árbol extraído sea cual sea el layout de BUILD de esta versión de rpm.
SRCDIR="$(dirname "$(find %{_topdir}/BUILD -type d -name linux_optimizer | head -1)")"
if [ ! -d "$SRCDIR/linux_optimizer" ]; then
    echo "No se encontró el árbol fuente en BUILD"; exit 1
fi
cd "$SRCDIR"
mkdir -p %{buildroot}%{_datadir}/%{name}
cp -a linux_optimizer %{buildroot}%{_datadir}/%{name}/
install -Dm755 run.sh %{buildroot}%{_bindir}/linux-optimizer
install -Dm644 packaging/linux-optimizer.desktop %{buildroot}%{_datadir}/applications/linux-optimizer.desktop
sed -i "s|@APPDIR@|%{_datadir}/%{name}|g; s|Exec=.*run.sh|Exec=%{_bindir}/linux-optimizer|" %{buildroot}%{_datadir}/applications/linux-optimizer.desktop
install -Dm644 linux_optimizer/resources/linux-optimizer.svg %{buildroot}%{_datadir}/icons/hicolor/scalable/apps/linux-optimizer.svg

%files
%doc README.md
%{_bindir}/linux-optimizer
%{_datadir}/%{name}/
%{_datadir}/applications/linux-optimizer.desktop
%{_datadir}/icons/hicolor/scalable/apps/linux-optimizer.svg

%changelog
* Mon Nov 17 2026 Daniel <daniel@localhost> - 0.1.0-1
- Primera versión empaquetada.
