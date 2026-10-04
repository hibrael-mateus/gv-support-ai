<#
  Build local completo no Windows (o mesmo que o GitHub Actions faz).
  Requisitos: Python 3.12, Node 22, Rust (rustup), WebView2 (já vem no Windows 10/11).
  Saída: release\GVSupportAI-Setup.exe e release\GVSupportAI.msi
#>
$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
Set-Location $root

python -m venv .venv
& .venv\Scripts\python -m pip install -r backend\requirements-dev.txt

Push-Location backend
& ..\.venv\Scripts\python -m pytest -q
& ..\.venv\Scripts\pyinstaller gv-support-backend.spec --noconfirm
Pop-Location

Push-Location desktop
npm ci
npx tauri build --bundles nsis,msi
Pop-Location

New-Item -ItemType Directory -Force release | Out-Null
Copy-Item (Get-ChildItem desktop\src-tauri\target\release\bundle\nsis\*.exe)[0] release\GVSupportAI-Setup.exe -Force
Copy-Item (Get-ChildItem desktop\src-tauri\target\release\bundle\msi\*.msi)[0] release\GVSupportAI.msi -Force
Get-ChildItem release
