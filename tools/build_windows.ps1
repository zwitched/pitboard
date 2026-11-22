# Build a one-file Windows console app. Run this on Windows, from the repo root,
# after the venv is active and PyInstaller is installed:
#   pip install pyinstaller
#   .\tools\build_windows.ps1

$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)

if (-not (Test-Path ".\.venv\Scripts\python.exe")) {
    Write-Error "Create .venv and install requirements before building."
}

& .\.venv\Scripts\python.exe -m PyInstaller `
    --noconfirm `
    --clean `
    --onefile `
    --name pitboard `
    --console `
    --add-data "web;web" `
    --add-data "schema\synthetic;schema\synthetic" `
    --collect-all grpc `
    --collect-all google `
    --collect-submodules pitboard `
    pitboard\__main__.py

Write-Host "Built dist\pitboard.exe"
Write-Host "Settings and logs are written next to the exe, in a data folder."
Write-Host "The executable is not signed. Windows SmartScreen may warn the first time you run it."
