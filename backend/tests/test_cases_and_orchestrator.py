import pytest

from app import cases
from app.agents import GVSupportOrchestrator
from app.agents.logs import analyze_log
from conftest import FakeProvider


def _case():
    return cases.create_case({"title": "Portal Professor apresenta erro ao gerar o diário", "customer": "Colégio X",
                              "product": "GVcollege", "module": "Portal do Professor", "server": "PV990",
                              "already_validated": "PV990 acessível = OK\nDNS PV990 = OK"})


def test_case_persistence_and_memory_from_opening():
    c = _case()
    again = cases.get_case(c["id"])
    assert again["number"] == f"#{c['id']:06d}"
    assert {f["key"]: f["status"] for f in again["facts"]} == {"PV990 acessível": "OK", "DNS PV990": "OK"}
    assert "DNS PV990 = OK [OK]" in cases.memory_text(c["id"])


def test_fact_upsert_does_not_duplicate():
    c = _case()
    cases.upsert_fact(c["id"], "TCP 1433", "OK")
    cases.upsert_fact(c["id"], "TCP 1433", "Timeout")
    facts = [f for f in cases.get_case(c["id"])["facts"] if f["key"] == "TCP 1433"]
    assert len(facts) == 1 and facts[0]["status"] == "FALHA"


def test_hypothesis_states_enforced_in_code():
    c = _case()
    h = cases.add_hypothesis(c["id"], "Application Pool parado")
    assert h["status"] == "Não validada"
    with pytest.raises(cases.EvidenceRequired):
        cases.update_hypothesis(h["id"], {"status": "Confirmada"})
    h = cases.update_hypothesis(h["id"], {"status": "Descartada", "evidence": "GVapp AppPool = Running"})
    assert h["status"] == "Descartada"


def test_secrets_are_masked_in_case_data():
    c = cases.create_case({"title": "Erro login", "description": "Server=PV;User Id=sa;Password=Sup3r!;"})
    assert "Sup3r" not in cases.get_case(c["id"])["description"]


def test_investigation_flow_updates_memory_and_hypotheses():
    c = _case()
    fake = FakeProvider(json_reply={
        "analysis": "Application Pool confirmado como Running. Hipótese 1 descartada.",
        "facts": [{"key": "GVapp AppPool", "value": "Running", "status": "OK"}],
        "hypotheses": [
            {"title": "Application Pool parado", "status": "Descartada", "evidence": "GVapp AppPool = Running"},
            {"title": "Erro da API", "status": "Confirmada", "evidence": ""},
            {"title": "Modelo de relatório", "status": "Em análise"},
        ],
        "next_step": "powershell", "powershell_focus": "IIS e logs", "root_cause": "API caiu",
    })
    out = GVSupportOrchestrator(fake).investigate(c["id"], "Resultado: GVapp AppPool Running")
    case = out["case"]
    statuses = {h["title"]: h["status"] for h in case["hypotheses"]}
    assert statuses == {"Application Pool parado": "Descartada", "Erro da API": "Muito provável", "Modelo de relatório": "Em análise"}
    assert any(f["key"] == "GVapp AppPool" for f in case["facts"])
    assert case["root_cause"] == ""  # not confirmed by evidence -> not recorded
    assert out["message"]["meta"]["scripts"][0]["language"] == "powershell"
    assert "MEMÓRIA DO CHAMADO" in fake.prompts[0][-1]["content"]
    assert "DNS PV990 = OK" in fake.prompts[0][-1]["content"]
    assert [m["role"] for m in cases.list_messages(c["id"])] == ["user", "assistant"]


def test_offline_investigation_still_produces_scripts():
    c = _case()
    out = GVSupportOrchestrator(FakeProvider(online=False)).investigate(c["id"])
    langs = [s["language"] for s in out["message"]["meta"]["scripts"]]
    assert "powershell" in langs and "IA offline" in out["message"]["content"]


def test_customer_response_and_n3():
    c = _case()
    orch = GVSupportOrchestrator(FakeProvider(online=False))
    resp = orch.investigate(c["id"], action="responder_cliente")["message"]["content"]
    assert "Colégio X" in resp and "tabela" not in resp.lower()
    out = orch.investigate(c["id"], action="escalonar_n3")
    text = out["message"]["content"]
    for section in ("Problema", "Comportamento atual", "Comportamento esperado", "Ambiente", "Passos para reprodução",
                    "Testes realizados", "Resultados", "Evidências", "Documentações relacionadas", "Hipótese técnica", "Anexos"):
        assert f"### {section}" in text
    assert out["case"]["status"] == "Escalonado N3"


def test_log_analysis_primary_and_consequent_errors():
    log = """2026-10-01 10:00:00 INFO Iniciando server=PV990
2026-10-01 10:00:01 WARN Pool lento
2026-10-01 10:00:02 ERROR System.Data.SqlClient.SqlException: Timeout expired
   at GV.Data.Repo.Execute()
   at GV.Portal.Diario.Gerar()
2026-10-01 10:00:03 ERROR Falha ao gerar relatório diário id=10
2026-10-01 10:00:04 ERROR Falha ao gerar relatório diário id=11
"""
    r = analyze_log(log)
    assert r["errors"] == 3 and r["warnings"] == 1
    assert r["primary_error"]["exception"] == "System.Data.SqlClient.SqlException"
    assert len(r["primary_error"]["stack"]) == 2
    assert r["consequent_errors"][0]["count"] == 2  # same signature grouped despite different ids
    assert "PV990" in r["servers"]


def test_route_intents():
    route = GVSupportOrchestrator.route
    assert route("gere um script powershell para o IIS") == "gerar_powershell"
    assert route("qual select para ver a tabela") == "gerar_sql"
    assert route("preciso escalonar para N3") == "escalonar_n3"
