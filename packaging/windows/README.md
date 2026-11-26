# Linux Optimizer + Cortex Gaming Engine para Windows

La misma aplicación tiene dos modos, **un solo ejecutable y una sola ventana**:

| Comando | Modo inicial |
|---|---|
| `LinuxOptimizer.exe` | Linux Optimizer |
| `LinuxOptimizer.exe --cortex` | Cortex Gaming Engine |

El botón **◈ Cortex Gaming Engine** cambia al modo Cortex en la misma ventana.
Desde Cortex, el botón **Linux Optimizer** vuelve al modo principal. No se abre
ninguna ventana ni proceso adicional. Cada modo conserva su tema, configuración
y registro propios.

## Compilar el .exe

Requisitos:

- Windows 10 u 11 de 64 bits.
- **Python 3.12 o 3.13 x64** desde [python.org](https://www.python.org/downloads/windows/)
  (marca «Add python.exe to PATH»).
- Conexión a Internet la primera vez (PyInstaller y dependencias).

Doble clic en:

```
packaging\windows\build-exe.bat
```

o desde PowerShell:

```powershell
.\packaging\windows\build-exe.ps1
```

El script crea `.venv-win`, instala PySide6, psutil y PyInstaller, regenera el
icono y produce:

```
dist\LinuxOptimizer.exe
```

PyInstaller **no puede compilar para Windows desde Linux**. El .exe debe
generarse en un equipo Windows (o en un runner `windows-latest` de GitHub
Actions con los mismos pasos). El repositorio incluye el flujo
`.github/workflows/windows-exe.yml`: sube una etiqueta `v*` o ejecuta el flujo
manualmente y descarga el artefacto `LinuxOptimizer-exe`.

### Ejecutar

```powershell
.\dist\LinuxOptimizer.exe
.\dist\LinuxOptimizer.exe --cortex
```

El primer arranque tarda unos segundos porque el .exe de un solo archivo se
descomprime en una carpeta temporal.

## Qué funciona en Windows

- **Panel de rendimiento**: CPU, RAM, swap, discos, red, GPU NVIDIA con
  `nvidia-smi` si está instalado.
- **Limpieza segura**: archivos temporales, caché de miniaturas y papelera de
  reciclaje.
- **Diagnóstico**: sistema, plan de energía, discos, memoria y temperatura.
- **Cortex Gaming Engine**:
  - Panel, CPU, RAM, Game Booster, Actividad y Ajustes.
  - Perfiles ECO/BALANCED/EXTREME mediante los planes de energía oficiales de
    Windows (`powercfg`), con instantánea del plan original y restauración.
  - Game Booster: detecta juegos en carpetas de Steam, Epic, GOG, Riot,
    Ubisoft y EA (o ventanas visibles) y asigna prioridad Alta del proceso
    con `psutil`, sin cerrar procesos ni pedir contraseña. Si no detecta el
    juego, usa «Selección manual» para elegir cualquier proceso en ejecución.
  - Configuración, registro e instantánea en `%APPDATA%` y `%LOCALAPPDATA%`.

## Limitaciones deliberadas en Windows

- **Servicios del sistema** y **Energía** se ocultan: dependen de systemd y de
  pkexec, que no existen en Windows. Los perfiles de Cortex usan `powercfg`.
- **HUD y FPS** no están portados: dependen de MangoHud, X11/XWayland y del
  socket `/tmp/mangoapp`.
- Cortex **no cambia relojes ni energía de GPU** en Windows; para eso usa el
  panel de NVIDIA, AMD o Intel. No se fuerza ningún valor a ciegas.
- Swappiness, `max_map_count`, `drop_caches` y governors de CPU no existen en
  Windows; se muestran como «no disponible» en lugar de fallar.
- Cambiar el plan activo con `powercfg /setactive` **normalmente funciona como
  usuario estándar**. Solo hace falta ejecutar la aplicación como
  administrador si Windows lo bloquea por directivas de grupo, por un plan
  personalizado/oculto por el fabricante o en equipos gestionados por la
  empresa. El resto de funciones nunca requiere elevación.

## Firma y SmartScreen

El .exe no está firmado. Windows SmartScreen puede mostrar «Windows protegió
tu PC»; usa **Más información → Ejecutar de todas formas** solo si confías en
el archivo que has compilado tú mismo.

## Estructura

```
packaging/windows/
├── linux-optimizer.spec   # Receta de PyInstaller (un solo .exe)
├── linux_optimizer_win.py # Punto de entrada del ejecutable
├── version_info.txt       # Metadatos de versión del .exe
├── make_icon.py           # Genera linux-optimizer.ico desde el SVG
├── requirements-build.txt # Dependencias de compilación
├── build-exe.ps1          # Compilación automatizada
└── build-exe.bat          # Lanzador de doble clic
```

El icono `linux_optimizer/resources/linux-optimizer.ico` ya está generado y
versionado; `make_icon.py` lo regenera si cambia el SVG.
