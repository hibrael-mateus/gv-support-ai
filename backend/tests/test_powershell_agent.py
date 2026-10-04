from app.agents.powershell import ALL_MODULES, build_diagnostic, guard_powershell, pick_modules
from app.security import classify_powershell


def test_full_diagnostic_is_read_only_and_exports_all_formats():
    s = build_diagnostic(ALL_MODULES, target="PV990", sql_instance="PV990\\SQL", urls=["https://portal"])
    assert not s.dangerous, s.reasons
    for needle in ("=== GV SUPPORT AI DIAGNÓSTICO ===", "Export-Csv", "ConvertTo-Json", "diagnostico.txt",
                   "Start-Transcript", "Compress-Archive", "Test-NetConnection", "Get-WinEvent", "Resolve-DnsName"):
        assert needle in s.code
    for forbidden in ("Stop-Service", "Restart-Service", "Remove-Item"):
        assert forbidden not in s.code


def test_parameters_are_quoted_safely():
    s = build_diagnostic(["rede"], target="host'; Remove-Item C:\\ -Recurse; '")
    assert "'host''; Remove-Item C:\\ -Recurse; '''" in s.code
    assert not s.dangerous  # injection stays inside a string literal


def test_module_selection_from_problem_text():
    mods = pick_modules("Portal Professor retorna HTTP 503 no IIS, app pool parado")
    assert "iis" in mods and "http" in mods and mods[0] == "sistema"


def test_destructive_scripts_are_flagged():
    for cmd in ("Restart-Service W3SVC", "Stop-Service MSSQLSERVER", "Remove-Item C:\\temp -Recurse",
                "Stop-WebAppPool GVapp", "Set-ItemProperty HKLM:\\x -Name y -Value 1"):
        assert classify_powershell(cmd).dangerous, cmd
    assert guard_powershell("Restart-Service W3SVC").warnings


def test_comments_do_not_trigger_danger():
    assert not classify_powershell("# Restart-Service W3SVC\nGet-Service W3SVC").dangerous
