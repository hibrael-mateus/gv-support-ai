"""Documentation, SimilarCase, Validation, CustomerResponse and N3Escalation agents."""
from __future__ import annotations

import re
from typing import Any

from .. import cases, rag
from ..llm import LLMProvider, LLMUnavailable
from ..rag import normalize
from .base import ANTI_HALLUCINATION, NO_EVIDENCE, AgentResult, sources_block

# Below this a hit is not treated as evidence. Calibrated on real TOPdesk KIs/tickets from the authorized folder:
# answerable tickets scored 62-100, questions about topics absent from the sources scored 16-49.
MIN_RELEVANCE = 55.0


class DocumentationAgent:
    name = "DocumentationAgent"

    def __init__(self, provider: LLMProvider | None = None):
        self.provider = provider

    def _embedder(self):
        return self.provider.embed if self.provider else None

    def search(self, query: str, limit: int = 6, min_relevance: float = MIN_RELEVANCE, **filters) -> list[dict[str, Any]]:
        hits = rag.search(query, limit, embedder=self._embedder(), **filters)
        return [h.as_dict() for h in hits if h.relevance >= min_relevance]

    def run(self, query: str, limit: int = 8, **filters) -> AgentResult:
        hits = self.search(query, limit, **filters)
        if not hits:
            return AgentResult(self.name, NO_EVIDENCE, [], meta={"evidence": False})
        lines = [f"Encontrei {len(hits)} trecho(s) relacionados nas fontes GV Dasa:"]
        for i, h in enumerate(hits, start=1):
            page = f", página {h['page']}" if h["page"] else ""
            lines.append(f"- **[F{i}] {h['source_name']}**{page} ({h['relevance']:.0f}%): {h['excerpt']}")
        return AgentResult(self.name, "\n".join(lines), hits, meta={"evidence": True})


class SimilarCaseAgent:
    name = "SimilarCaseAgent"

    def __init__(self, docs: DocumentationAgent):
        self.docs = docs

    def run(self, text: str, case_id: int | None = None) -> AgentResult:
        local = cases.similar_local_cases(text, exclude_id=case_id)
        hits = [h for h in self.docs.search(text, 8) if h["doc_type"] in ("KI", "Chamado", "FAQ", "Procedimento")] \
            or self.docs.search(text, 5)
        items = []
        for c in local:
            items.append({"similarity": c["similarity"], "problem": c["title"], "previous_cause": c["root_cause"] or "-",
                          "previous_solution": c["resolution"] or "-", "source": f"Chamado local {c['number']}",
                          "case_id": c["id"]})
        for h in hits:
            items.append({"similarity": round(h["relevance"]), "problem": h["excerpt"][:220],
                          "previous_cause": _field(h["content"], ("causa", "motivo")),
                          "previous_solution": _field(h["content"], ("solução", "solucao", "resolução", "correção", "procedimento")),
                          "source": h["source_name"] + (f" (pág. {h['page']})" if h["page"] else ""),
                          "drive_file_id": h["drive_file_id"]})
        items.sort(key=lambda x: -x["similarity"])
        if not items:
            return AgentResult(self.name, "Nenhum caso semelhante encontrado nas fontes ou no histórico local.", [])
        md = ["| Similaridade | Problema | Causa anterior | Solução anterior | Fonte |", "|---|---|---|---|---|"]
        for it in items[:8]:
            md.append("| {}% | {} | {} | {} | {} |".format(
                it["similarity"], *(str(it[k]).replace("|", "/").replace("\n", " ")[:160]
                                    for k in ("problem", "previous_cause", "previous_solution", "source"))))
        md.append("\n> Casos anteriores são referência: **valide o cenário atual antes de aplicar qualquer solução antiga.**")
        return AgentResult(self.name, "\n".join(md), hits, meta={"similar": items[:8]})


def _field(content: str, labels: tuple[str, ...]) -> str:
    for label in labels:
        m = re.search(rf"{label}\w*\s*[:\-–]\s*(.+)", content, re.I)
        if m:
            return m.group(1).strip()[:200]
    # TOPdesk tickets carry no labelled fields: the latest history entry (newest first) usually holds the answer.
    hist = re.split(r"Histórico técnico e tratativas\W*", content, maxsplit=1)
    if len(hist) == 2 and "solu" in labels[0]:
        return re.sub(r"\s+", " ", hist[1]).strip()[:200] or "-"
    return "-"


class ValidationAgent:
    """Programmatic anti-hallucination checks on any LLM output."""

    name = "ValidationAgent"
    GV_SPECIFIC = re.compile(r"\b(gv\w*|tabela|coluna|procedure|view|trigger|par[aâ]metro|tela|rotina|menu|regra|"
                             r"portal|pergamum|matr[ií]cula|di[aá]rio|nota|rtm|ki)\b", re.I)

    def is_gv_specific(self, text: str) -> bool:
        return bool(self.GV_SPECIFIC.search(text or ""))

    def check_answer(self, answer: str, hits: list[dict[str, Any]], question: str) -> tuple[str, list[str]]:
        issues: list[str] = []
        cited = {int(n) for n in re.findall(r"\[F(\d+)\]", answer)}
        invalid = sorted(n for n in cited if n < 1 or n > len(hits))
        if invalid:
            issues.append(f"Citações inexistentes removidas: {', '.join(f'F{n}' for n in invalid)}")
            for n in invalid:
                answer = answer.replace(f"[F{n}]", "[fonte não encontrada]")
        if self.is_gv_specific(question) and not hits and NO_EVIDENCE not in answer:
            answer = f"> {NO_EVIDENCE}\n\n" + answer
            issues.append("Pergunta específica GV Dasa sem evidência nas fontes.")
        return answer, issues

    @staticmethod
    def sanitize_hypothesis(h: dict[str, Any]) -> dict[str, Any]:
        status = h.get("status") or "Não validada"
        if status not in cases.HYPOTHESIS_STATUSES:
            status = "Em análise"
        if status in ("Confirmada", "Descartada") and not str(h.get("evidence") or "").strip():
            status = "Muito provável" if status == "Confirmada" else "Em análise"
        return {**h, "status": status}


class CustomerResponseAgent:
    name = "CustomerResponseAgent"

    def __init__(self, provider: LLMProvider | None):
        self.provider = provider

    def run(self, case: dict[str, Any], extra: str = "") -> AgentResult:
        confirmed = [h for h in case["hypotheses"] if h["status"] == "Confirmada"]
        cause = case.get("root_cause") or (confirmed[0]["title"] if confirmed else "")
        if self.provider:
            prompt = (
                "Escreva a resposta ao cliente para o chamado abaixo, como se fosse o próprio analista de suporte da GV Dasa. "
                "Português do Brasil, profissional, direto, objetivo, cordial, sem excesso de termos técnicos, sem citar "
                "ferramentas internas, IA, hipóteses descartadas ou nomes de tabelas. Se a causa não estiver confirmada, "
                "informe o andamento e o próximo passo, sem prometer prazos. Não use Markdown pesado; texto pronto para colar.\n\n"
                f"Cliente: {case['customer']}\nProduto/Módulo: {case['product']} / {case['module']}\n"
                f"Problema relatado: {case['title']}\n{case['description']}\nMensagem de erro: {case['error_message']}\n"
                f"Causa confirmada: {cause or 'ainda não confirmada'}\nCorreção aplicada/proposta: {case.get('resolution') or '-'}\n"
                f"Testes realizados: {cases.memory_text(case['id']) or '-'}\n{extra}"
            )
            try:
                text = self.provider.chat([{"role": "system", "content": "Você redige comunicações de suporte."},
                                           {"role": "user", "content": prompt}])
                return AgentResult(self.name, text.strip())
            except LLMUnavailable:
                pass
        greeting = f"Olá{', ' + case['customer'] if case['customer'] else ''}!"
        if cause:
            body = (f"Concluímos a análise do problema relatado ({case['title']}). Identificamos que a causa era: {cause}. "
                    f"{case.get('resolution') or 'Aplicamos o ajuste necessário.'} "
                    "Pedimos, por gentileza, que valide novamente o mesmo procedimento e nos retorne caso o comportamento persista.")
        else:
            body = (f"Estamos analisando o problema relatado ({case['title']}). Já realizamos verificações no ambiente e "
                    "seguimos investigando para identificar a causa. Assim que tivermos a confirmação, retornaremos com a solução.")
        return AgentResult(self.name, f"{greeting}\n\n{body}\n\nFicamos à disposição.\n\nAtenciosamente,")


class N3EscalationAgent:
    name = "N3EscalationAgent"

    def __init__(self, provider: LLMProvider | None):
        self.provider = provider

    def run(self, case: dict[str, Any], sources: list[dict[str, Any]]) -> AgentResult:
        facts = case["facts"]
        tests = "\n".join(f"- {f['key']}" for f in facts) or "- Nenhum teste registrado"
        results = "\n".join(f"- {f['key']} = {f['value']} [{f['status']}]" for f in facts) or "- Sem resultados registrados"
        hyps = "\n".join(f"- {h['title']} — **{h['status']}**" + (f" (evidência: {h['evidence']})" if h["evidence"] else "")
                         for h in case["hypotheses"]) or "- Nenhuma hipótese registrada"
        main_hyp = next((h for h in case["hypotheses"] if h["status"] in ("Confirmada", "Muito provável")), None)
        docs = "\n".join(f"- {s['source_name']}" + (f" (pág. {s['page']})" if s.get("page") else "") for s in sources) \
            or "- Nenhuma documentação GV Dasa relacionada encontrada"
        attachments = "\n".join(f"- {a['name']}" for a in case["attachments"]) or "- Nenhum"
        env = ", ".join(x for x in (case["environment"], f"Servidor: {case['server']}" if case["server"] else "",
                                    f"Banco: {case['database_name']}" if case["database_name"] else "") if x) or "Não informado"
        steps = " > ".join(x for x in (case["product"], case["module"], case["menu"], case["routine"], case["screen"]) if x)
        text = f"""## Escalonamento N3 — Chamado {case['number']}

### Problema
{case['title']}
Cliente: {case['customer'] or '-'} | Produto: {case['product'] or '-'} | Módulo: {case['module'] or '-'}

### Comportamento atual
{case['description'] or '-'}
{('Mensagem de erro: `' + case['error_message'] + '`') if case['error_message'] else ''}

### Comportamento esperado
[Descrever o comportamento esperado conforme documentação/regra de negócio]

### Ambiente
{env}

### Passos para reprodução
1. Acessar {steps or '[caminho da tela]'}
2. [Ação executada]
3. Observar: {case['error_message'] or '[resultado]'}

### Testes realizados
{tests}

### Resultados
{results}

### Evidências
{hyps}

### Documentações relacionadas
{docs}

### Hipótese técnica
{(main_hyp['title'] + ' — ' + main_hyp['status'] + (': ' + main_hyp['rationale'] if main_hyp['rationale'] else '')) if main_hyp else 'Nenhuma hipótese confirmada até o momento.'}

### Anexos
{attachments}
"""
        return AgentResult(self.name, text, sources)


def evidence_known_text(case: dict[str, Any] | None, hits: list[dict[str, Any]], extra: str = "") -> str:
    """Everything that counts as confirmed structure: sources, case memory, attachments, analyst messages."""
    parts = [h["content"] for h in hits] + [extra]
    if case:
        parts += [f"{f['key']} {f['value']}" for f in case["facts"]]
        parts.append(cases.attachment_texts(case["id"], 20000))
        parts += [m["content"] for m in cases.list_messages(case["id"], 60) if m["role"] == "user"]
    return normalize("\n".join(parts))


SYSTEM_BASE = "Você é o GV Support AI, especialista técnico de suporte da GV Dasa.\n" + ANTI_HALLUCINATION


def source_context(hits: list[dict[str, Any]]) -> str:
    return "EVIDÊNCIAS GV DASA:\n" + sources_block(hits) if hits else "EVIDÊNCIAS GV DASA: nenhuma evidência encontrada."
