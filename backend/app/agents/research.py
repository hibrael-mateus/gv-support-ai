"""ResearchAgent: the chat's answer loop over the GV Dasa sources.

Analysts ask in their own words ("como eu emito o boletim no portal 2.0"); KIs use the product's words
("Emissão de boletim escolar", "Portal do Professor 2.0 > Notas"). A single keyword search with a fixed cut-off
missed those, so the agent:
1. searches with the question; a strong match goes straight to the answer;
2. otherwise asks the model for search queries in the documents' vocabulary and searches again;
3. gives the model the best candidates, lets it pick the ones that really answer and say what is missing;
4. searches once more with what it said is missing, then answers citing only the sources it used.
Without a model it falls back to the strict keyword gate (MIN_RELEVANCE).
"""
from __future__ import annotations

import re
from typing import Any

from ..llm import LLMProvider, LLMUnavailable, parse_json_loose
from .base import NO_EVIDENCE, sources_block
from .specialists import DocumentationAgent

STRONG = 75.0  # a hit this good answers without rewriting the query
CANDIDATE_MIN = 30.0  # below this a chunk shares little more than a product name with the question
MAX_CANDIDATES = 8

PLAN_PROMPT = """Você planeja buscas numa base de conhecimento de suporte da GV Dasa (KIs do TOPdesk, manuais,
release notes e chamados resolvidos dos produtos GVcollege, Portal do Professor 2.0, Portal do Aluno 2.0, GVcentris,
GVmobile, GVpay, GVnfse, Gestão de Contratos e outros).
Reescreva a pergunta do analista em 3 consultas curtas (3 a 8 palavras cada) usando as palavras que estariam escritas
no documento: substantivos em vez de verbos conjugados (ex.: "emito" → "emissão"), nome do produto, tela, menu, rotina,
mensagem de erro e sinônimos. Não invente nomes de tabelas.
Responda SOMENTE JSON: {"queries": ["...", "...", "..."]}"""

ANSWER_PROMPT = """Você é o GV Support AI, especialista de suporte da GV Dasa, respondendo a um analista.
Use SOMENTE os trechos em EVIDÊNCIAS GV DASA para fatos da GV Dasa (telas, menus, parâmetros, regras, procedimentos,
tabelas). Muitos trechos vêm de uma busca e podem não ter relação com a pergunta: ignore os que não respondem.
Conhecimento genérico de Windows, IIS, SQL Server, .NET, rede e navegadores pode ser usado normalmente.
Nunca invente nomes de tabelas, colunas, telas ou parâmetros. Cite cada afirmação GV Dasa com [F1], [F2]...

Responda SOMENTE JSON:
{
  "answer": "resposta em Markdown, em português do Brasil, direta e em passos quando for procedimento, com citações [Fn]",
  "used": [números dos trechos citados],
  "missing": "se os trechos não bastam: o que faltou, em 3 a 8 palavras de busca; senão vazio"
}
Se nenhum trecho responde a pergunta, "answer" deve começar exatamente com: "%s" e dizer em uma frase o que foi encontrado
de mais próximo, e "used" deve ser []."""


class ResearchAgent:
    name = "ResearchAgent"

    def __init__(self, provider: LLMProvider | None, docs: DocumentationAgent):
        self.provider = provider
        self.docs = docs

    # ---- retrieval --------------------------------------------------------
    def _gather(self, queries: list[str], pool: dict[str, dict[str, Any]]) -> None:
        for q in queries:
            for h in self.docs.search(q, MAX_CANDIDATES, min_relevance=CANDIDATE_MIN):
                key = f"{h['drive_file_id']}|{h['source_name']}|{h['page']}"
                if key not in pool or h["relevance"] > pool[key]["relevance"]:
                    pool[key] = h

    @staticmethod
    def _top(pool: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
        return sorted(pool.values(), key=lambda h: -h["relevance"])[:MAX_CANDIDATES]

    def _plan(self, question: str, history: list[dict[str, str]]) -> list[str]:
        context = "\n".join(f"{m['role']}: {m['content'][:300]}" for m in history[-4:])
        try:
            data = parse_json_loose(self.provider.chat(
                [{"role": "system", "content": PLAN_PROMPT},
                 {"role": "user", "content": (f"CONVERSA ANTERIOR:\n{context}\n\n" if context else "") + f"PERGUNTA: {question}"}],
                json_mode=True))
        except LLMUnavailable:
            return []
        return [str(q).strip() for q in data.get("queries") or [] if str(q).strip()][:4]

    # ---- answer -----------------------------------------------------------
    def _answer(self, question: str, hits: list[dict[str, Any]], history: list[dict[str, str]], extra: str) -> dict[str, Any]:
        evidence = "EVIDÊNCIAS GV DASA:\n" + sources_block(hits) if hits else "EVIDÊNCIAS GV DASA: nenhuma."
        raw = self.provider.chat(
            [{"role": "system", "content": ANSWER_PROMPT % NO_EVIDENCE}, *history,
             {"role": "user", "content": f"{evidence}\n\n{extra}PERGUNTA DO ANALISTA:\n{question}"}],
            json_mode=True)
        data = parse_json_loose(raw)
        if not isinstance(data.get("answer"), str):  # a small local model may ignore the JSON format
            data = {"answer": raw.strip(), "used": [int(n) for n in re.findall(r"\[F(\d+)\]", raw)], "missing": ""}
        return data

    def run(self, question: str, history: list[dict[str, str]], extra: str = "",
            general_ok: bool = False) -> tuple[str, list[dict[str, Any]], dict[str, Any]]:
        """(answer, cited sources, meta). Raises LLMUnavailable when the model fails mid-way.
        general_ok: the question is about generic technology, so it may be answered without GV sources."""
        pool: dict[str, dict[str, Any]] = {}
        self._gather([question], pool)
        queries: list[str] = []
        if not pool or self._top(pool)[0]["relevance"] < STRONG:
            queries = self._plan(question, history)
            self._gather(queries, pool)
        hits = self._top(pool)
        if not hits and not general_ok:  # nothing to read: never let the model answer a GV question from memory
            return NO_EVIDENCE, [], {"queries": queries, "candidates": 0}
        data = self._answer(question, hits, history, extra)
        missing = str(data.get("missing") or "").strip()
        if missing and (not data.get("used") or str(data.get("answer", "")).startswith(NO_EVIDENCE)):
            before = set(pool)
            self._gather([missing], pool)
            if set(pool) - before:
                queries.append(missing)
                hits = self._top(pool)
                data = self._answer(question, hits, history, extra)
        return self._finish(data, hits, queries)

    @staticmethod
    def _finish(data: dict[str, Any], hits: list[dict[str, Any]], queries: list[str]):
        answer = str(data.get("answer") or "").strip() or NO_EVIDENCE
        used = sorted({int(n) for n in re.findall(r"\[F(\d+)\]", answer)} |
                      {int(n) for n in data.get("used") or [] if str(n).isdigit()})
        used = [n for n in used if 1 <= n <= len(hits)]
        if answer.startswith(NO_EVIDENCE) and not re.search(r"\[F\d+\]", answer):
            used = []
        # Renumber so the answer's [Fn] match the order of the sources shown under it.
        cited = [hits[n - 1] for n in used]
        mapping = {old: new for new, old in enumerate(used, start=1)}
        answer = re.sub(r"\[F(\d+)\]", lambda m: f"[F{mapping[int(m.group(1))]}]" if int(m.group(1)) in mapping
                        else "[fonte não encontrada]", answer)
        return answer, cited, {"queries": queries, "candidates": len(hits)}

