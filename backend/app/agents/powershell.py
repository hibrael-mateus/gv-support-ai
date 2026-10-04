"""PowerShellAgent: read-only diagnostic scripts for Windows Server / IIS / SQL Server / network.

Related checks are combined into ONE script that also exports TXT, CSV, JSON, LOG and ZIP.
Generated scripts never stop/restart services or delete files; the danger classifier double-checks.
"""
from __future__ import annotations

import re

from ..security import classify_powershell
from .base import ANTI_HALLUCINATION, Script

MODULES: dict[str, tuple[str, str]] = {
    "sistema": ("Sistema", r"""
Invoke-GVCheck 'Sistema' {
  $os = Get-CimInstance Win32_OperatingSystem
  $cpu = Get-CimInstance Win32_Processor | Measure-Object -Property LoadPercentage -Average
  [pscustomobject]@{
    Computador   = $os.CSName
    SO           = $os.Caption
    Versao       = $os.Version
    UltimoBoot   = $os.LastBootUpTime
    UptimeHoras  = [math]::Round(((Get-Date) - $os.LastBootUpTime).TotalHours, 1)
    CPUPercent   = [math]::Round($cpu.Average, 1)
    RAMTotalGB   = [math]::Round($os.TotalVisibleMemorySize / 1MB, 2)
    RAMLivreGB   = [math]::Round($os.FreePhysicalMemory / 1MB, 2)
    RAMUsoPercent = [math]::Round(100 - ($os.FreePhysicalMemory / $os.TotalVisibleMemorySize * 100), 1)
  }
}"""),
    "disco": ("Disco", r"""
Invoke-GVCheck 'Disco' {
  Get-CimInstance Win32_LogicalDisk -Filter "DriveType=3" | ForEach-Object {
    [pscustomobject]@{
      Unidade      = $_.DeviceID
      TamanhoGB    = [math]::Round($_.Size / 1GB, 1)
      LivreGB      = [math]::Round($_.FreeSpace / 1GB, 1)
      LivrePercent = [math]::Round($_.FreeSpace / $_.Size * 100, 1)
      Alerta       = if ($_.FreeSpace / $_.Size -lt 0.10) { 'ESPACO CRITICO' } else { '' }
    }
  }
}"""),
    "servicos": ("Serviços", r"""
Invoke-GVCheck 'Servicos automaticos parados' {
  Get-CimInstance Win32_Service | Where-Object { $_.StartMode -eq 'Auto' -and $_.State -ne 'Running' } |
    Select-Object Name, DisplayName, State, StartMode, StartName
}
Invoke-GVCheck 'Servicos relevantes' {
  Get-Service | Where-Object { $_.Name -match $ServicePattern -or $_.DisplayName -match $ServicePattern } |
    Select-Object Name, DisplayName, Status, StartType
}"""),
    "processos": ("Processos", r"""
Invoke-GVCheck 'Processos por CPU' {
  Get-Process | Sort-Object CPU -Descending | Select-Object -First 15 Name, Id, CPU,
    @{n='MemoriaMB';e={[math]::Round($_.WorkingSet64 / 1MB, 1)}}, StartTime
}
Invoke-GVCheck 'Processos por memoria' {
  Get-Process | Sort-Object WorkingSet64 -Descending | Select-Object -First 15 Name, Id,
    @{n='MemoriaMB';e={[math]::Round($_.WorkingSet64 / 1MB, 1)}}
}"""),
    "iis": ("IIS", r"""
Invoke-GVCheck 'IIS - Application Pools' {
  Import-Module WebAdministration -ErrorAction Stop
  Get-ChildItem IIS:\AppPools | Select-Object Name, State, ManagedRuntimeVersion, ManagedPipelineMode,
    @{n='Identidade';e={$_.processModel.identityType}}
}
Invoke-GVCheck 'IIS - Sites' {
  Import-Module WebAdministration -ErrorAction Stop
  Get-Website | Select-Object Name, State, PhysicalPath, ApplicationPool,
    @{n='Bindings';e={($_.bindings.Collection | ForEach-Object { $_.protocol + ' ' + $_.bindingInformation }) -join '; '}}
}
Invoke-GVCheck 'IIS - Worker processes' {
  Get-CimInstance Win32_Process -Filter "Name='w3wp.exe'" | Select-Object ProcessId,
    @{n='AppPool';e={ if ($_.CommandLine -match '-ap "([^"]+)"') { $Matches[1] } }},
    @{n='MemoriaMB';e={[math]::Round($_.WorkingSetSize / 1MB, 1)}}, CreationDate
}"""),
    "rede": ("Rede", r"""
Invoke-GVCheck 'DNS' { Resolve-DnsName $Target -ErrorAction Stop | Select-Object Name, Type, IPAddress, NameHost }
Invoke-GVCheck 'Conectividade' {
  foreach ($p in $Ports) {
    $t = Test-NetConnection -ComputerName $Target -Port $p -WarningAction SilentlyContinue
    [pscustomobject]@{ Alvo = $Target; Porta = $p; TcpOK = $t.TcpTestSucceeded; IP = $t.RemoteAddress; PingOK = $t.PingSucceeded }
  }
}
Invoke-GVCheck 'Portas em escuta' {
  Get-NetTCPConnection -State Listen | Sort-Object LocalPort | Select-Object LocalAddress, LocalPort,
    @{n='Processo';e={(Get-Process -Id $_.OwningProcess -ErrorAction SilentlyContinue).Name}}
}"""),
    "sql": ("SQL Server", r"""
Invoke-GVCheck 'SQL Server - servicos' {
  Get-Service | Where-Object { $_.Name -like 'MSSQL*' -or $_.Name -like 'SQLAgent*' -or $_.Name -eq 'SQLBrowser' } |
    Select-Object Name, Status, StartType
}
Invoke-GVCheck 'SQL Server - porta' {
  $t = Test-NetConnection -ComputerName $SqlServer -Port $SqlPort -WarningAction SilentlyContinue
  [pscustomobject]@{ Servidor = $SqlServer; Porta = $SqlPort; TcpOK = $t.TcpTestSucceeded }
}
Invoke-GVCheck 'SQL Server - SELECT 1 (autenticacao integrada, somente leitura)' {
  $cn = New-Object System.Data.SqlClient.SqlConnection "Server=$SqlInstance;Database=master;Integrated Security=True;Connect Timeout=10"
  $cn.Open()
  $cmd = $cn.CreateCommand()
  $cmd.CommandText = "SELECT 1 AS ok, @@SERVERNAME AS servidor, CAST(SERVERPROPERTY('ProductVersion') AS varchar(30)) AS versao, SYSDATETIME() AS data_hora"
  $r = $cmd.ExecuteReader(); $null = $r.Read()
  $o = [pscustomobject]@{ SELECT1 = $r['ok']; Servidor = $r['servidor']; Versao = $r['versao']; DataHora = $r['data_hora'] }
  $cn.Close(); $o
}"""),
    "eventos": ("Event Viewer", r"""
Invoke-GVCheck 'Eventos de erro (Application/System)' {
  Get-WinEvent -FilterHashtable @{ LogName = 'Application','System'; Level = 1,2; StartTime = (Get-Date).AddHours(-$Hours) } -MaxEvents 200 -ErrorAction Stop |
    Select-Object TimeCreated, LogName, ProviderName, Id, LevelDisplayName,
      @{n='Mensagem';e={ ($_.Message -split "`n")[0] }}
}
Invoke-GVCheck 'Eventos agrupados por origem' {
  Get-WinEvent -FilterHashtable @{ LogName = 'Application','System'; Level = 1,2; StartTime = (Get-Date).AddHours(-$Hours) } -MaxEvents 1000 -ErrorAction Stop |
    Group-Object ProviderName, Id | Sort-Object Count -Descending | Select-Object -First 20 Count, Name
}"""),
    "certificados": ("Certificados", r"""
Invoke-GVCheck 'Certificados (LocalMachine\My)' {
  Get-ChildItem Cert:\LocalMachine\My | Select-Object Subject, Issuer, NotBefore, NotAfter, Thumbprint,
    @{n='DiasRestantes';e={ [int]($_.NotAfter - (Get-Date)).TotalDays }},
    @{n='Alerta';e={ if ($_.NotAfter -lt (Get-Date)) { 'EXPIRADO' } elseif ($_.NotAfter -lt (Get-Date).AddDays(30)) { 'EXPIRA EM < 30 DIAS' } else { '' } }}
}"""),
    "tarefas": ("Tarefas agendadas", r"""
Invoke-GVCheck 'Tarefas agendadas com falha' {
  Get-ScheduledTask | Where-Object { $_.State -ne 'Disabled' -and $_.TaskPath -notlike '\Microsoft\*' } | ForEach-Object {
    $i = $_ | Get-ScheduledTaskInfo
    [pscustomobject]@{ Tarefa = $_.TaskName; Caminho = $_.TaskPath; Estado = $_.State; UltimaExecucao = $i.LastRunTime; UltimoResultado = $i.LastTaskResult }
  } | Where-Object { $_.UltimoResultado -ne 0 }
}"""),
    "http": ("HTTP/HTTPS", r"""
Invoke-GVCheck 'HTTP/HTTPS' {
  [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
  foreach ($u in $Urls) {
    $sw = [Diagnostics.Stopwatch]::StartNew()
    try {
      $resp = Invoke-WebRequest -Uri $u -UseBasicParsing -TimeoutSec 20 -MaximumRedirection 3
      [pscustomobject]@{ Url = $u; Status = $resp.StatusCode; LatenciaMs = $sw.ElapsedMilliseconds; Erro = '' }
    } catch {
      $code = if ($_.Exception.Response) { [int]$_.Exception.Response.StatusCode } else { 0 }
      [pscustomobject]@{ Url = $u; Status = $code; LatenciaMs = $sw.ElapsedMilliseconds; Erro = $_.Exception.Message }
    }
  }
}"""),
    "logs": ("Arquivos de log", r"""
Invoke-GVCheck 'Logs recentes' {
  if (-not (Test-Path $LogPath)) { throw "Pasta de log nao encontrada: $LogPath" }
  Get-ChildItem -Path $LogPath -Recurse -Include *.log, *.txt -ErrorAction SilentlyContinue |
    Sort-Object LastWriteTime -Descending | Select-Object -First 10 FullName, Length, LastWriteTime
}
Invoke-GVCheck 'Erros nos logs recentes' {
  Get-ChildItem -Path $LogPath -Recurse -Include *.log, *.txt -ErrorAction SilentlyContinue |
    Sort-Object LastWriteTime -Descending | Select-Object -First 5 |
    Select-String -Pattern 'error|erro|exception|fatal|timeout' |
    Select-Object -Last 100 Filename, LineNumber, @{n='Linha';e={ $_.Line.Trim() }}
}"""),
}

ALL_MODULES = list(MODULES)
DEFAULT_MODULES = ["sistema", "disco", "servicos", "rede", "eventos"]

KEYWORDS = {
    "iis": r"iis|app ?pool|application pool|w3wp|site|portal|http 50\d|503|500",
    "sql": r"sql|banco|database|1433|timeout de conex|login failed",
    "rede": r"rede|dns|porta|conex|ping|firewall|latên|lent",
    "certificados": r"certificad|ssl|tls|https|expirad",
    "tarefas": r"tarefa|agendad|job|rotina noturna|schedule",
    "http": r"http|api|url|endpoint|portal|web",
    "processos": r"cpu|mem[oó]ria|ram|lent|travad|congel|processo",
    "disco": r"disco|espa[cç]o|storage|cheio",
    "logs": r"\blog\b|logs",
    "eventos": r"event|evento|erro|falha|crash",
}


def pick_modules(text: str) -> list[str]:
    found = [m for m, pat in KEYWORDS.items() if re.search(pat, text or "", re.I)]
    return list(dict.fromkeys(["sistema", *found, "eventos"])) if found else DEFAULT_MODULES


def _ps_str(value: str) -> str:
    return "'" + (value or "").replace("'", "''") + "'"


def build_diagnostic(
    modules: list[str] | None = None,
    *,
    target: str = "",
    sql_instance: str = "",
    urls: list[str] | None = None,
    log_path: str = "",
    hours: int = 24,
    service_pattern: str = "GV|IIS|W3SVC|WAS|MSSQL",
    title: str = "Diagnóstico GV Support AI",
) -> Script:
    modules = [m for m in (modules or DEFAULT_MODULES) if m in MODULES] or DEFAULT_MODULES
    sql_server = (sql_instance.split("\\")[0].split(",")[0]) if sql_instance else ""
    sql_port = sql_instance.split(",")[1] if "," in sql_instance else "1433"
    url_list = ", ".join(_ps_str(u) for u in (urls or [])) or "''"
    body = "\n".join(MODULES[m][1].strip("\n") for m in modules)
    p_target = _ps_str(target) if target else "$env:COMPUTERNAME"
    p_instance = _ps_str(sql_instance) if sql_instance else "$env:COMPUTERNAME"
    p_server = _ps_str(sql_server) if sql_server else "$env:COMPUTERNAME"
    p_logs = _ps_str(log_path) if log_path else "'C:\\inetpub\\logs\\LogFiles'"
    names = ", ".join(MODULES[m][0] for m in modules)
    code = f"""#Requires -Version 5.1
<#
  GV Support AI - {title}
  Módulos: {names}
  Script SOMENTE LEITURA: não para/reinicia serviços, não altera configuração e não remove arquivos.
  Resultado exportado em TXT, CSV, JSON, LOG e ZIP na pasta $OutDir.
#>
param(
  [string]$Target = {p_target},
  [string]$SqlInstance = {p_instance},
  [string]$SqlServer = {p_server},
  [int]$SqlPort = {sql_port},
  [string[]]$Urls = @({url_list}),
  [int[]]$Ports = @(80, 443, 1433, 3389),
  [string]$LogPath = {p_logs},
  [int]$Hours = {int(hours)},
  [string]$ServicePattern = {_ps_str(service_pattern)},
  [string]$OutDir = (Join-Path $env:TEMP ('GVSupportAI-Diagnostico-' + (Get-Date -Format 'yyyyMMdd-HHmmss')))
)

$ErrorActionPreference = 'Continue'
$null = New-Item -ItemType Directory -Force -Path $OutDir
Start-Transcript -Path (Join-Path $OutDir 'diagnostico.log') | Out-Null
$Report = [ordered]@{{}}
$Summary = New-Object System.Collections.Generic.List[string]

function Invoke-GVCheck([string]$Name, [scriptblock]$Block) {{
  Write-Host ""
  Write-Host "=== $Name ===" -ForegroundColor Cyan
  try {{
    $result = @(& $Block)
    $Report[$Name] = $result
    $text = ($result | Format-Table -AutoSize | Out-String -Width 250).Trim()
    if (-not $text) {{ $text = '(sem resultados)' }}
    Write-Host $text
    $Summary.Add("=== $Name ===`r`n$text`r`n")
    $safe = ($Name -replace '[^\\w]+', '_')
    if ($result.Count -gt 0 -and $result[0] -is [psobject]) {{
      $result | Export-Csv -Path (Join-Path $OutDir "$safe.csv") -NoTypeInformation -Encoding UTF8
    }}
  }} catch {{
    $Report[$Name] = "ERRO: $($_.Exception.Message)"
    Write-Warning "$Name -> $($_.Exception.Message)"
    $Summary.Add("=== $Name ===`r`nERRO: $($_.Exception.Message)`r`n")
  }}
}}

Write-Host "=== GV SUPPORT AI DIAGNÓSTICO ===" -ForegroundColor Green
Write-Host "Computador: $env:COMPUTERNAME | Alvo: $Target | Data: $(Get-Date -Format 'dd/MM/yyyy HH:mm:ss')"

{body}

$Summary | Out-File -FilePath (Join-Path $OutDir 'diagnostico.txt') -Encoding UTF8
$Report | ConvertTo-Json -Depth 5 | Out-File -FilePath (Join-Path $OutDir 'diagnostico.json') -Encoding UTF8
Stop-Transcript | Out-Null
$zip = "$OutDir.zip"
Compress-Archive -Path (Join-Path $OutDir '*') -DestinationPath $zip -Force
Write-Host ""
Write-Host "Resultados exportados (TXT, CSV, JSON, LOG): $OutDir" -ForegroundColor Green
Write-Host "Pacote ZIP: $zip" -ForegroundColor Green
Write-Host "Cole o conteúdo de diagnostico.txt no GV Support AI para continuar a investigação."
"""
    danger = classify_powershell(code)
    return Script("powershell", title, code, danger.dangerous, danger.reasons)


def guard_powershell(code: str, title: str = "PowerShell gerado") -> Script:
    danger = classify_powershell(code)
    warnings = ["Script contém comandos que alteram o ambiente. Revise antes de executar; nunca execute em produção sem janela de manutenção."] if danger.dangerous else []
    return Script("powershell", title, code, danger.dangerous, danger.reasons, warnings)


PS_SYSTEM = (
    "Você é o PowerShellAgent do GV Support AI, especialista em Windows Server, IIS, SQL Server e redes.\n"
    + ANTI_HALLUCINATION + "\n"
    "Gere scripts PowerShell 5.1 de INVESTIGAÇÃO (somente leitura) usando cmdlets oficiais: Test-NetConnection, "
    "Resolve-DnsName, Get-Service, Get-Process, Get-WinEvent, Get-ScheduledTask, Get-CimInstance, Get-NetTCPConnection, "
    "Invoke-WebRequest, Invoke-RestMethod, Select-String, Get-ChildItem, Get-Content. Nunca use Stop-Service, "
    "Restart-Service, Remove-Item ou Set-* sem que o analista peça explicitamente uma correção. "
    "Formato: JSON {\"explanation\": markdown, \"scripts\": [{\"title\": str, \"powershell\": str}]}."
)
