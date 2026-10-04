from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

NO_EVIDENCE = "Não encontrei evidência suficiente nas fontes GV Dasa disponíveis para confirmar essa informação."

ANTI_HALLUCINATION = (
    "REGRAS OBRIGATÓRIAS:\n"
    "1. Fatos específicos da GV Dasa (tabelas, colunas, views, procedures, triggers, parâmetros, telas, rotinas, regras "
    "de negócio, processos internos) só podem vir das EVIDÊNCIAS GV DASA fornecidas. Cite-as como [F1], [F2]...\n"
    f"2. Sem evidência suficiente para um fato GV Dasa, escreva exatamente: \"{NO_EVIDENCE}\" e proponha como descobrir "
    "(consultas a INFORMATION_SCHEMA/sys.*, scripts de diagnóstico).\n"
    "3. Nunca invente nomes de tabelas, colunas ou procedures. Se a estrutura não está nas evidências, gere consultas de descoberta.\n"
    "4. Nunca trate hipótese como causa confirmada sem evidência objetiva (resultado de teste, log, consulta).\n"
    "5. Nunca comece por UPDATE/DELETE: DESCOBRIR → SELECT → ANALISAR → ALTERAR (em transação) → VALIDAR.\n"
    "6. Não peça novamente testes que já constam na MEMÓRIA DO CHAMADO.\n"
    "7. Conhecimento genérico de Windows, IIS, SQL Server, PowerShell, .NET, rede e TLS pode ser usado normalmente.\n"
    "8. Responda em português do Brasil, de forma técnica, objetiva e organizada em Markdown."
)


@dataclass
class Script:
    language: str  # sql | powershell
    title: str
    code: str
    dangerous: bool = False
    reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


@dataclass
class AgentResult:
    agent: str
    content: str
    sources: list[dict[str, Any]] = field(default_factory=list)
    scripts: list[Script] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {"agent": self.agent, "content": self.content, "sources": self.sources,
                "scripts": [s.as_dict() for s in self.scripts], "meta": self.meta}


def sources_block(hits: list[dict[str, Any]]) -> str:
    lines = []
    for i, h in enumerate(hits, start=1):
        page = f" | Página {h['page']}" if h.get("page") else ""
        lines.append(f"[F{i}] {h['source_name']}{page} | Tipo: {h.get('doc_type') or '-'} | "
                     f"Produto: {h.get('product') or '-'}\n{h['content']}")
    return "\n\n".join(lines)
