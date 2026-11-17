# Cómo instalar Linux Optimizer en otra PC

Elige según la distribución de la máquina destino.

---

## Opción A — Fedora (RPM) — instalación "de sistema"

1. Compila el RPM en esta PC (requiere `sudo dnf install -y rpm-build`):

   ```bash
   ./packaging/build-rpm.sh
   ```

   El RPM queda en `packaging/rpm/build/RPMS/noarch/linux-optimizer-0.1.0-*.noarch.rpm`

2. Copia ese archivo `.rpm` a la otra Fedora (USB, `scp`, etc.) e instala:

   ```bash
   sudo dnf install ./linux-optimizer-0.1.0-*.noarch.rpm
   ```

   `dnf` resuelve automáticamente las dependencias (`python3-pyside6`,
   `python3-psutil`, `polkit`).

3. Busca «Linux Optimizer» en el menú, o ejecuta `linux-optimizer` en terminal.

Desinstalar: `sudo dnf remove linux-optimizer`

---

## Opción B — Cualquier Linux (portable) — Ubuntu, Debian, Arch, Fedora, etc.

1. Genera el paquete portable en esta PC:

   ```bash
   ./packaging/build-portable.sh
   ```

2. Copia `packaging/portable/linux-optimizer-*-portable.tar.gz` a la otra PC
   (USB, `scp`, Drive…) y en un terminal:

   ```bash
   tar -xzf linux-optimizer-*-portable.tar.gz
   cd linux-optimizer-*-portable

   # 1) Dependencias de Python (sin tocar el sistema):
   python3 -m venv .venv
   .venv/bin/pip install -r requirements.txt

   # 2) Probar:
   ./run.sh

   # 3) (Opcional) entrada en el menú de aplicaciones + ícono:
   ./install-menu.sh
   ```

Requisitos de la PC destino: `python3` (≥ 3.10), `pip` y escritorio gráfico.

En Debian/Ubuntu quizá falte `python3-venv`: `sudo apt install python3-venv`.
En Arch: `sudo pacman -S --needed python-pip`.

Desinstalar: borra la carpeta y, si usaste el menú,
`rm ~/.local/share/applications/linux-optimizer.desktop`

---

## Notas de seguridad

- La app eleva privilegios **solo con pkexec** y pide confirmación antes de
  cada cambio; no requiere ejecutarla con sudo.
- Los respaldos quedan en `~/.local/share/LinuxOptimizer/backups/` de cada PC.
- El RPM instala en `/usr/share/linux-optimizer` con `python3-pyside6` del
  sistema; el portable usa su propio `.venv` aislado.
