# Linux Optimizer

Herramienta gráfica profesional para optimizar y administrar el rendimiento de
computadoras Linux. Interfaz moderna, oscura, desarrollada en **Python +
PySide6 + psutil + Qt Stylesheets (QSS)**.

## Características

| Módulo | Descripción |
|---|---|
| 🖥 **Panel de rendimiento** | CPU (total y por núcleo), RAM, swap, GPU, temperaturas, disco (uso e I/O) y red, en tiempo real con gráficos. |
| 🧹 **Limpieza segura** | Caché de usuario, miniaturas, papelera, caché del gestor de paquetes (dnf/apt/pacman), journal y runtimes flatpak sin uso. |
| 🎮 **Modo Gaming** | Optimizaciones temporales y reversibles: governor de CPU, detener Bluetooth/CUPS/Avahi, vaciar caché. Detecta GameMode (Feral). |
| ⚙️ **Servicios del sistema** | Listado de unidades systemd con estado; iniciar/detener/reiniciar/habilitar/deshabilitar con protección de servicios esenciales. |
| 🔋 **Energía** | Detección automática del backend (power-profiles-daemon, tuned o governor de CPU) y cambio de perfil con respaldo. |
| 🩺 **Diagnóstico** | Comprobaciones de solo lectura: arranque, unidades en fallo, errores del journal y del kernel, discos, memoria, temperatura, swappiness, governor. Informe copiable. |
| ℹ️ **Acerca de** | Información del entorno, historial de respaldos con apertura/eliminación. |

Además: icono en la bandeja del sistema (si el escritorio lo soporta), integración
con el menú de aplicaciones y GPU con métricas en vivo para NVIDIA (nvidia-smi)
y AMD (sysfs: `gpu_busy_percent`, VRAM, hwmon).

## Compatibilidad

- **Objetivo inicial:** Fedora (probado en Fedora 44, KDE/GNOME).
- **Arquitectura preparada para:** Ubuntu, Debian y Arch (detección por
  familia en `linux_optimizer/core/distro.py`, que selecciona el gestor de
  paquetes, las reglas de limpieza y el backend de energía).

## Seguridad (diseño por contrato)

1. **Nada destructivo automático.** Toda acción que modifica el sistema pasa
   por un diálogo de confirmación explícito.
2. **Elevación solo con pkexec** (polkit): la contraseña la pide el agente
   gráfico del escritorio; la app nunca pide ni guarda contraseñas.
3. **Respaldos automáticos.** Antes de detener/deshabilitar un servicio, o de
   cambiar un perfil de energía o el governor, se crea un snapshot en
   `~/.local/share/LinuxOptimizer/backups/` con el estado previo.
4. **Restauración.** Cada módulo ofrece «Restaurar»: servicios (estado previo),
   energía (perfil anterior) y modo gaming (revierte todas las acciones).
5. **Servicios esenciales protegidos.** systemd, dbus, NetworkManager, sddm,
   polkit, logind, firewalld, sshd, etc. **no pueden** detenerse ni
   deshabilitarse desde la aplicación (lista `ESSENTIAL_KEYWORDS` en
   `linux_optimizer/core/services.py`, cubierta por pruebas).
6. **Compatibilidad mostrada.** Si una optimización no es compatible con el
   hardware o la distribución (p. ej. governor en una VM), se marca como
   «no compatible» y se explica por qué.

## Instalación y ejecución

```bash
# Dependencias (Fedora)
sudo dnf install python3-pyside6 python3-psutil

# o con un entorno virtual
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

./run.sh          # o: .venv/bin/python -m linux_optimizer
```

### Integración con el escritorio

```bash
packaging/install-desktop.sh   # ícono + entrada en el menú (sin root)
```

Para generar un RPM en Fedora:

```bash
rpmbuild -bb packaging/linux-optimizer.spec
```

## Estructura del proyecto

```
linux_optimizer/
├── app.py                  # Bootstrap de QApplication + tema
├── main_window.py          # Ventana principal, navegación lateral
├── theme/style.qss         # Tema oscuro profesional (QSS)
├── core/                   # Lógica sin dependencias de UI
│   ├── distro.py           #   Detección de distro/escritorio (fedora|debian|arch)
│   ├── hardware.py         #   Detección de CPU, GPU, discos, sensores, batería
│   ├── monitor.py          #   Monitorización en vivo (psutil + QTimer)
│   ├── cleaner.py          #   Objetivos de limpieza (scan/clean seguros)
│   ├── services.py         #   systemd + lista de servicios esenciales
│   ├── power.py            #   Perfiles de energía (ppd/tuned/governor)
│   ├── kernel.py           #   Swappiness con persistencia y restauración
│   ├── gaming.py           #   Acciones del modo gaming (reversibles)
│   ├── diagnostics.py      #   Comprobaciones de solo lectura
│   ├── backup.py           #   Snapshots y restauración
│   └── permissions.py      #   run() / run_privileged() (pkexec)
└── ui/                     # Páginas y widgets (dashboard, cleaner, gaming…)
tests/                      # Pruebas (pytest): lógica y smoke test GUI
run.sh                      # Lanzador
```

## Pruebas

```bash
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest tests/ -v
```

Las pruebas cubren detección de distro, respaldos (crear/restaurar), reglas de
limpieza, protección de servicios esenciales y un smoke test de la GUI en modo
offscreen.
