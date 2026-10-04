<#
  Publica uma nova versão: atualiza o número em todos os arquivos, cria o commit e a tag vX.Y.Z.
  Ao enviar a tag, o GitHub Actions gera o instalador e cria o Release; o app instalado
  passa a oferecer a atualização em Configurações > Atualizações.

  Uso: .\scripts\release.ps1 1.1.0
#>
param([Parameter(Mandatory)][ValidatePattern('^\d+\.\d+\.\d+$')][string]$Version)
$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent

function Set-Text($path, $pattern, $replacement) {
  $full = Join-Path $root $path
  $text = [IO.File]::ReadAllText($full)
  $new = [regex]::Replace($text, $pattern, $replacement, 1)
  if ($new -eq $text) { throw "Versão não encontrada em $path" }
  [IO.File]::WriteAllText($full, $new)
}

Set-Text "desktop/src-tauri/tauri.conf.json" '"version": "[^"]+"' "`"version`": `"$Version`""
Set-Text "desktop/src-tauri/Cargo.toml" '(?m)^version = "[^"]+"' "version = `"$Version`""
Set-Text "desktop/package.json" '"version": "[^"]+"' "`"version`": `"$Version`""
Set-Text "backend/app/__init__.py" '__version__ = "[^"]+"' "__version__ = `"$Version`""

git -C $root add -A
git -C $root commit -m "Release v$Version"
git -C $root tag "v$Version"
Write-Host "Pronto. Envie com: git push origin main --tags"
