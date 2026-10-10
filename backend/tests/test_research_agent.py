import json

from app.agents import GVSupportOrchestrator
from app.agents.base import NO_EVIDENCE
from conftest import index_sample


class ScriptedProvider:
    """Answers each call with the next scripted reply and records every prompt."""

    name = "scripted"

    def __init__(self, *replies):
        self.replies = list(replies)
        self.prompts = []

    def status(self):
        return {"online": True, "models": ["s"], "model": "s"}

    def list_models(self):
        return ["s"]

    def chat(self, messages, json_mode=False):
        self.prompts.append(messages)
        reply = self.replies.pop(0)
        return reply if isinstance(reply, str) else json.dumps(reply)

    def embed(self, texts):
        return None


def _seed():
    index_sample("KI 3901 - Portal do Professor 2.0 - Emissão de boletim",
                 "Para a emissão do boletim escolar no Portal do Professor 2.0, acesse Notas > Boletim, selecione a turma "
                 "e clique em Gerar PDF. O boletim só aparece depois do fechamento da etapa.", file_id="ki-boletim")
    index_sample("KI 1200 - GVcollege - Rematrícula bloqueada",
                 "A rematrícula exibe bloqueio quando há pendência financeira ativa no cadastro do aluno.", file_id="ki-remat")


def test_rewrites_the_question_into_the_documents_words_and_cites_what_it_used():
    _seed()
    llm = ScriptedProvider({"queries": ["emissão boletim escolar Portal do Professor 2.0", "gerar PDF boletim turma"]},
                           {"answer": "Acesse Notas > Boletim e clique em Gerar PDF [F1].", "used": [1], "missing": ""})
    msg = GVSupportOrchestrator(llm).chat("onde eu imprimo as notas finais da turma pro aluno levar pra casa?")["message"]
    assert "Gerar PDF [F1]" in msg["content"]
    assert [s["drive_file_id"] for s in msg["sources"]] == ["ki-boletim"]
    assert msg["meta"]["queries"][0].startswith("emissão boletim")
    assert "Notas > Boletim" in llm.prompts[1][-1]["content"]  # the KI reached the model as evidence


def test_only_cited_sources_are_shown_and_citations_are_renumbered():
    _seed()
    llm = ScriptedProvider({"queries": ["boletim", "rematrícula pendência"]},
                           {"answer": "O bloqueio vem de pendência financeira [F2].", "used": [2], "missing": ""})
    msg = GVSupportOrchestrator(llm).chat("por que o portal bloqueia a rematrícula e o boletim?")["message"]
    assert "[F1]" in msg["content"] and "[F2]" not in msg["content"]
    assert len(msg["sources"]) == 1


def test_model_rejecting_every_candidate_gives_no_evidence_without_sources():
    _seed()
    llm = ScriptedProvider({"queries": ["catraca portaria"]},
                           {"answer": NO_EVIDENCE + " O mais próximo foi uma KI de boletim.", "used": [], "missing": ""})
    msg = GVSupportOrchestrator(llm).chat("Como configurar a catraca da portaria no Portal do Professor 2.0?")["message"]
    assert msg["content"].startswith(NO_EVIDENCE) and msg["sources"] == []


def test_searches_again_with_what_the_model_said_was_missing():
    _seed()
    llm = ScriptedProvider({"queries": ["boletim turma"]},
                           {"answer": NO_EVIDENCE, "used": [], "missing": "rematrícula pendência financeira"},
                           {"answer": "É a pendência financeira [F2].", "used": [2], "missing": ""})
    msg = GVSupportOrchestrator(llm).chat("o aluno não consegue renovar a vaga para o próximo semestre, por quê?")["message"]
    assert msg["sources"] and msg["sources"][0]["drive_file_id"] == "ki-remat"
    assert len(llm.prompts) == 3


def test_gv_question_with_nothing_found_never_reaches_the_answer_step():
    _seed()
    llm = ScriptedProvider({"queries": ["catraca biométrica portaria"]})
    msg = GVSupportOrchestrator(llm).chat("Como cadastrar a biometria da catraca no GVcentris?")["message"]
    assert msg["content"] == NO_EVIDENCE and len(llm.prompts) == 1


def test_plain_text_reply_from_a_small_model_still_works():
    _seed()
    llm = ScriptedProvider("isto não é JSON", "Use Notas > Boletim [F1].")
    msg = GVSupportOrchestrator(llm).chat("boletim do portal do professor 2.0, como emitir?")["message"]
    assert msg["content"] == "Use Notas > Boletim [F1]." and msg["sources"]
