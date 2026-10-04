from app.agents import GVSupportOrchestrator
from app.agents.base import NO_EVIDENCE
from app.agents.specialists import ValidationAgent
from conftest import FakeProvider, index_sample


def test_gv_question_without_evidence_returns_exact_sentence_and_skips_llm():
    fake = FakeProvider(chat_reply="A tabela ALUNO_NOTAS guarda as notas.")
    out = GVSupportOrchestrator(fake).chat("Qual tabela do GVcollege guarda as notas?")
    assert out["message"]["content"].startswith(NO_EVIDENCE)
    assert fake.prompts == []  # the LLM was never asked to make it up


def test_sql_question_without_evidence_offers_discovery_queries():
    out = GVSupportOrchestrator(FakeProvider()).chat("Qual tabela do GVcollege guarda as notas? gere o SQL")
    scripts = out["message"]["meta"]["scripts"]
    assert out["message"]["content"].startswith(NO_EVIDENCE)
    assert scripts and "INFORMATION_SCHEMA.COLUMNS" in scripts[0]["code"]


def test_invalid_citations_are_removed():
    answer, issues = ValidationAgent().check_answer("Conforme [F1] e [F7].", [{"x": 1}], "pergunta")
    assert "[F7]" not in answer and "[F1]" in answer and issues


def test_hypothesis_cannot_be_confirmed_without_evidence():
    h = ValidationAgent.sanitize_hypothesis({"title": "AppPool parado", "status": "Confirmada", "evidence": ""})
    assert h["status"] == "Muito provável"


def test_answer_with_evidence_goes_through_llm_with_sources():
    index_sample("KI 3220 - GVcollege x Pergamum WEB", "A integração com Pergamum WEB usa a URL do webservice.", file_id="ki")
    fake = FakeProvider(chat_reply="Configure a URL do webservice [F1].")
    out = GVSupportOrchestrator(fake).chat("Como configurar integração Pergamum no GVcollege?")
    assert "[F1]" in out["message"]["content"]
    assert out["message"]["sources"][0]["drive_file_id"] == "ki"
    assert "EVIDÊNCIAS GV DASA" in fake.prompts[0][-1]["content"]
