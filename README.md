# Linux Optimizer + Cortex Gaming Engine

Herramienta gráfica profesional para optimizar y administrar el rendimiento
del equipo, desarrollada en **Python + PySide6 + psutil + Qt Stylesheets
(QSS)**. Es **una sola aplicación con dos sesiones**:

| Sesión | Acceso |
|---|---|
| Linux Optimizer | `linux-optimizer` (o `LinuxOptimizer.exe` en Windows) |
| Cortex Gaming Engine | `linux-optimizer --cortex` (o `LinuxOptimizer.exe --cortex`) |

Ambas comparten el ejecutable y los detectores de hardware, pero tienen su
propia ventana, tema, configuración, monitorización y registro. El botón
**◈ Cortex Gaming Engine** abre Cortex sin cerrar Linux Optimizer; el botón
**Linux Optimizer** de Cortex hace el camino inverso.

## Características

| Módulo | Descripción |
|---|---|
| ◈ **Cortex Gaming Engine** | Sesión gaming: Panel, Perfiles ECO/BALANCED/EXTREME, CPU, GPU, RAM, Game Booster (detección automática o selección manual del proceso), Actividad y Ajustes, con tema verde propio y guardado/restauración independientes. |
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

- **Objetivo inicial:** Fedora (probado en Fedora 44, GNOME/Wayland).
- **Arquitectura preparada para:** Ubuntu, Debian y Arch (detección por
  familia en `linux_optimizer/core/distro.py`, que selecciona el gestor de
  paquetes, las reglas de limpieza y el backend de energía).
- **Windows 10/11 x64:** mismo `.exe` para las dos sesiones. Las páginas que
  dependen de systemd/pkexec se ocultan; Cortex usa `powercfg` y prioridad
  nativa de procesos. Ver `packaging/windows/README.md`.

## Seguridad (diseño por contrato)

1. **Nada destructivo automático.** Toda acción que modifica el sistema pasa
   por un diálogo de confirmación explícito.
2. **Elevación solo con pkexec en Linux** (polkit): la contraseña la pide el
   agente gráfico del escritorio; la app nunca pide ni guarda contraseñas. En
   Windows no se usa pkexec: Cortex aplica los perfiles con `powercfg`.
3. **Respaldos automáticos.** Antes de detener/deshabilitar un servicio, o de
   cambiar un perfil de energía o el governor, se crea un snapshot con el
   estado previo (en Linux `~/.local/share/LinuxOptimizer/backups/` y en
   Windows `%LOCALAPPDATA%\LinuxOptimizer\backups`).
4. **Restauración.** Cada módulo ofrece «Restaurar»: servicios (estado previo),
   energía (perfil anterior), modo gaming (revierte todas las acciones) y
   Cortex (plan de energía original).
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

### Ejecutable de Windows (.exe)

En un equipo Windows 10/11 x64 con Python 3.12/3.13:

```powershell
packaging\windows\build-exe.ps1
```

o doble clic en `packaging\windows\build-exe.bat`. Se genera
`dist\LinuxOptimizer.exe`, que abre Linux Optimizer o la sesión Cortex con
`--cortex`. Instrucciones completas y limitaciones en
`packaging/windows/README.md`.

## Estructura del proyecto

```
linux_optimizer/
├── app.py                  # Bootstrap de QApplication + tema
├── main_window.py          # Ventana principal, navegación lateral
├── theme/style.qss         # Tema oscuro profesional (QSS)
├── core/                   # Lógica sin dependencias de UI
│   ├── distro.py           #   Detección de sistema (fedora|debian|arch|windows)
│   ├── platform_info.py    #   Detección de plataforma en tiempo de ejecución
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
cortex_engine/              # Sesión Cortex (tema, módulos, perfiles, registro)
├── interface/              #   Ventana, páginas, tema QSS y widgets propios
├── cpu/ gpu/ memory/       #   Controles por hardware (+ adaptadores Windows)
├── profiles/               #   ECO/BALANCED/EXTREME, lote y restauración
├── gaming/                 #   Game Booster (pkexec en Linux / psutil en Windows)
├── monitoring/ restore/    #   Monitor, registro y snapshot propios
packaging/windows/          #   Build del .exe (PyInstaller) y documentación
tests/                      # Pruebas (pytest): lógica, Windows y smoke test GUI
run.sh                      # Lanzador
```

## Pruebas

```bash
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest tests/ -v
```

Las pruebas cubren detección de distro, respaldos (crear/restaurar), reglas de
limpieza, protección de servicios esenciales, las dos sesiones de la aplicación,
los flujos de Windows (simulados en Linux con dobles de `powercfg`/`psutil`),
el empaquetado `.exe` y un smoke test de la GUI en modo offscreen.

El `.exe` real solo puede compilarse en Windows (o en el flujo de GitHub
Actions); las pruebas verifican los archivos y la configuración del
empaquetado.
