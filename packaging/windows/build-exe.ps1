# Construye LinuxOptimizer.exe en Windows 10/11 (x64).
#
#   packaging\windows\build-exe.ps1
#
# Crea un entorno virtual .venv-win, instala las dependencias y PyInstaller,
# regenera el icono .ico y empaqueta la aplicación completa en un solo archivo:
#   dist\LinuxOptimizer.exe
#
# El .exe contiene las dos sesiones de la aplicación:
#   LinuxOptimizer.exe             → Linux Optimizer
#   LinuxOptimizer.exe --cortex    → Cortex Gaming Engine

[CmdletBinding()]
param(
    [switch]$SkipInstall,
    [switch]$KeepBuild
)

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$Venv = Join-Path $Root ".venv-win"
$Python = Join-Path $Venv "Scripts\python.exe"

Push-Location $Root
try {
    if (-not (Test-Path $Python)) {
        Write-Host "Creando entorno virtual en $Venv ..."
        $Launcher = Get-Command py -ErrorAction SilentlyContinue
        if ($Launcher) {
            & py -3 -m venv $Venv
        } else {
            & python -m venv $Venv
        }
        if ($LASTEXITCODE -ne 0) {
            throw "No se pudo crear el entorno virtual. Instala Python 3.12/3.13 x64 desde python.org."
        }
    }

    if (-not $SkipInstall) {
        Write-Host "Instalando dependencias ..."
        & $Python -m pip install --upgrade pip
        & $Python -m pip install -r "packaging\windows\requirements-build.txt"
        if ($LASTEXITCODE -ne 0) {
            throw "Falló la instalación de dependencias."
        }
    }

    Write-Host "Generando icono .ico ..."
    & $Python "packaging\windows\make_icon.py"
    if ($LASTEXITCODE -ne 0) {
        throw "No se pudo generar el icono."
    }

    if (-not $KeepBuild) {
        Remove-Item -Recurse -Force "build\LinuxOptimizer" -ErrorAction SilentlyContinue
    }

    Write-Host "Empaquetando con PyInstaller ..."
    & $Python -m PyInstaller --noconfirm --clean "packaging\windows\linux-optimizer.spec"
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller terminó con error."
    }

    $Exe = Join-Path $Root "dist\LinuxOptimizer.exe"
    if (-not (Test-Path $Exe)) {
        throw "No se encontró $Exe."
    }
    $Size = [math]::Round((Get-Item $Exe).Length / 1MB, 1)
    Write-Host ""
    Write-Host "[OK] Listo: $Exe ($Size MB)" -ForegroundColor Green
    Write-Host "  Linux Optimizer:            .\dist\LinuxOptimizer.exe"
    Write-Host "  Cortex Gaming Engine:       .\dist\LinuxOptimizer.exe --cortex"
} finally {
    Pop-Location
}
