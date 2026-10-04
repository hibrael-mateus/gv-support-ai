"""GVSupportOrchestrator: decides which specialist agents to run for each step of an investigation.

Flow: CHAMADO → entender → fontes GV → evidências → hipóteses → testes (SQL/PowerShell/procedimento)
→ analisar resultados → descartar hipóteses → causa raiz → correção → validação → resposta ao cliente.
"""
from __future__ import annotations

import json
import re
from typing import Any

from .. import cases, internet
from ..llm import LLMProvider, LLMUnavailable, get_provider
from ..settings import load_config
from .base import NO_EVIDENCE, AgentResult, Script
from .logs import analyze_log, summary_markdown
from .powershell import PS_SYSTEM, build_diagnostic, guard_powershell, pick_modules
from .specialists import (SYSTEM_BASE, CustomerResponseAgent, DocumentationAgent, N3EscalationAgent,
                          SimilarCaseAgent, ValidationAgent, evidence_known_text, source_context)
from .sql import SQL_SYSTEM, discovery_script, guard_sql

ACTIONS = {
    "investigar": "Investigar",
    "pesquisar_fontes": "Pesquisar fontes",
    "gerar_sql": "Gerar SQL",
    "gerar_powershell": "Gerar PowerShell",
    "analisar_log": "Analisar log",
    "caso_semelhante": "Buscar caso semelhante",
    "interpretar_resultado": "Interpretar resultado",
    "responder_cliente": "Responder cliente",
    "escalonar_n3": "Escalonar N3",
}

INTENTS = [
    ("escalonar_n3", r"escalon|\bn3\b|n[ií]vel 3"),
    ("responder_cliente", r"respond\w* (ao |o )?cliente|resposta (ao|para o) cliente|e-?mail (ao|para o) cliente"),
    ("caso_semelhante", r"caso[s]? semelhante|similar|j[aá] aconteceu|parecid"),
    ("analisar_log", r"analis\w* (o |este |esse )?log|stack ?trace|\bexception\b.*\n.*\bat\b"),
    ("gerar_sql", r"\bsql\b|select|consulta|query|tabela|coluna|procedure|banco de dados"),
    ("gerar_powershell", r"powershell|\bps1\b|script de diagn|servidor|\biis\b|servi[cç]o do windows|event viewer|dns|porta"),
    ("pesquisar_fontes", r"pesquis|procur|document|manual|\bki\b|fonte"),
]

INVESTIGATION_JSON = """Responda SOMENTE com JSON válido neste formato:
{
  "analysis": "texto em Markdown para o analista: o que se sabe, o que as fontes dizem (cite [F1]...), o que os resultados colados indicam e qual o próximo passo",
  "facts": [{"key": "teste/verificação executada", "value": "resultado objetivo", "status": "OK|FALHA|INFO"}],
  "hypotheses": [{"title": "hipótese", "rationale": "por quê", "test": "como validar", "status": "Não validada|Em análise|Muito provável|Confirmada|Descartada", "evidence": "evidência objetiva (obrigatória para Confirmada/Descartada)"}],
  "next_step": "powershell|sql|procedimento|cliente|n3|nenhum",
  "powershell_focus": "o que o script PowerShell deve investigar (se next_step=powershell)",
  "sql_goal": "o que a consulta SQL deve descobrir (se next_step=sql)",
  "root_cause": "causa raiz SOMENTE se confirmada por evidência; senão vazio",
  "fix": "correção proposta SOMENTE se a causa estiver confirmada; senão vazio"
}
"facts" deve conter apenas resultados que o analista informou (ex.: "DNS PV990" = "OK"). Atualize hipóteses existentes pelo mesmo título."""


class GVSupportOrchestrator:
    def __init__(self, provider: LLMProvider | None = None):
        self.provider = provider or get_provider()
        self.cfg = load_config()
        self._online: bool | None = None
        self.docs = DocumentationAgent(self.provider)
        self.similar = SimilarCaseAgent(self.docs)
        self.validation = ValidationAgent()

    # ---- helpers ---------------------------------------------------------
    def online(self) -> bool:
        if self._online is None:
            try:
                self._online = bool(self.provider.status().get("online"))
            except Exception:
                self._online = False
        return self._online

    def _llm(self) -> LLMProvider | None:
        return self.provider if self.online() else None

    @staticmethod
    def route(text: str) -> str:
        for intent, pattern in INTENTS:
            if re.search(pattern, text or "", re.I):
                return intent
        return "investigar"

    @staticmethod
    def case_query(case: dict[str, Any], extra: str = "") -> str:
        return " ".join(str(case.get(k) or "") for k in ("title", "product", "module", "routine", "screen", "error_message")) \
            + " " + (case.get("description") or "")[:300] + " " + extra[:300]

    @staticmethod
    def case_brief(case: dict[str, Any]) -> str:
        fields = [("Chamado", case["number"]), ("Título", case["title"]), ("Cliente", case["customer"]),
                  ("Produto", case["product"]), ("Módulo", case["module"]), ("Rotina", case["routine"]),
                  ("Menu", case["menu"]), ("Tela", case["screen"]), ("Mensagem de erro", case["error_message"]),
                  ("Descrição", case["description"]), ("Ambiente", case["environment"]), ("Servidor", case["server"]),
                  ("Banco de dados", case["database_name"]), ("Status", case["status"])]
        brief = "\n".join(f"{k}: {v}" for k, v in fields if v)
        memory = cases.memory_text(case["id"])
        hyps = "\n".join(f"- {h['title']} [{h['status']}] {('evidência: ' + h['evidence']) if h['evidence'] else ''}"
                         for h in case["hypotheses"])
        return (f"DADOS DO CHAMADO:\n{brief}\n\nMEMÓRIA DO CHAMADO (testes já realizados, não repetir):\n{memory or '(vazia)'}"
                f"\n\nHIPÓTESES ATUAIS:\n{hyps or '(nenhuma)'}")

    def _history(self, case_id: int | None, n: int = 8) -> list[dict[str, str]]:
        msgs = cases.list_messages(case_id, n)
        return [{"role": "assistant" if m["role"] == "assistant" else "user", "content": m["content"][:4000]} for m in msgs]

    # ---- free chat ---------------------------------------------------------
    def chat(self, message: str, use_sources: bool = True, case_id: int | None = None) -> dict[str, Any]:
        intent = self.route(message)
        if case_id:
            return self.investigate(case_id, message, intent)
        cases.add_message(None, "user", message)
        result = self._free_chat(message, use_sources, intent)
        msg = cases.add_message(None, "assistant", result.content, result.agent, result.sources,
                                {"scripts": [s.as_dict() for s in result.scripts], **result.meta})
        return {"message": msg}

    def _free_chat(self, message: str, use_sources: bool, intent: str) -> AgentResult:
        hits = self.docs.search(message, 6) if use_sources else []
        if intent == "analisar_log":
            res = analyze_log(message)
            return AgentResult("LogAnalysisAgent", summary_markdown(res), meta={"log": res})
        if intent == "caso_semelhante":
            return self.similar.run(message)
        if intent == "pesquisar_fontes":
            return self.docs.run(message)
        scripts: list[Script] = []
        if intent == "gerar_powershell":
            scripts.append(build_diagnostic(pick_modules(message)))
        llm = self._llm()
        gv_specific = self.validation.is_gv_specific(message)
        if use_sources and not hits and gv_specific and intent not in ("gerar_powershell",):
            extra = []
            if intent == "gerar_sql":
                extra.append(discovery_script(_terms(message)))
            content = NO_EVIDENCE
            if extra:
                content += "\n\nPara descobrir a estrutura no banco do cliente, execute as consultas de descoberta abaixo (somente leitura)."
            return AgentResult("ValidationAgent", content, [], extra)
        if not llm:
            content = ("**IA offline** — configure o Ollama em Configurações > Inteligência Artificial.\n\n"
                       + (self.docs.run(message).content if hits else ""))
            if intent == "gerar_sql":
                scripts.append(discovery_script(_terms(message)))
            return AgentResult("GVSupportOrchestrator", content, hits, scripts, {"llm": False})
        web = []
        if self.cfg.get("internet_enabled") and not gv_specific and intent in ("investigar", "gerar_powershell"):
            web = internet.search_microsoft_learn(message, 3)
        system = SQL_SYSTEM if intent == "gerar_sql" else PS_SYSTEM if intent == "gerar_powershell" else SYSTEM_BASE
        user = f"{source_context(hits)}\n\n" + (
            "REFERÊNCIAS MICROSOFT (complemento externo):\n" + "\n".join(f"- {w['title']}: {w['url']}" for w in web) + "\n\n" if web else "") \
            + f"PERGUNTA DO ANALISTA:\n{message}"
        try:
            if intent in ("gerar_sql", "gerar_powershell"):
                data = self.provider.chat_json([{"role": "system", "content": system}, *self._history(None, 4),
                                                {"role": "user", "content": user}])
                answer = data.get("explanation") or ""
                scripts += self._scripts_from_llm(data, None, hits, message)
            else:
                answer = self.provider.chat([{"role": "system", "content": system}, *self._history(None, 6),
                                             {"role": "user", "content": user}])
        except LLMUnavailable as exc:
            return AgentResult("GVSupportOrchestrator", f"**IA indisponível:** {exc}", hits, scripts, {"llm": False})
        answer, issues = self.validation.check_answer(answer, hits, message)
        if web:
            answer += "\n\n**Referências Microsoft:**\n" + "\n".join(f"- [{w['title']}]({w['url']})" for w in web)
        return AgentResult("GVSupportOrchestrator", answer, hits, scripts, {"validation": issues, "web": web})

    def _scripts_from_llm(self, data: dict[str, Any], case: dict[str, Any] | None, hits: list[dict[str, Any]],
                          extra: str) -> list[Script]:
        out: list[Script] = []
        known = evidence_known_text(case, hits, extra)
        for item in data.get("scripts") or []:
            if not isinstance(item, dict):
                continue
            if item.get("sql"):
                out += guard_sql(str(item["sql"]), known, item.get("title") or "SQL")
            elif item.get("powershell"):
                out.append(guard_powershell(str(item["powershell"]), item.get("title") or "PowerShell"))
        return out

    # ---- case investigation ------------------------------------------------
    def investigate(self, case_id: int, message: str = "", action: str = "investigar") -> dict[str, Any]:
        case = cases.get_case(case_id)
        if message:
            cases.add_message(case_id, "user", message, meta={"action": action})
        elif action != "investigar":
            cases.add_message(case_id, "user", f"[Ação rápida] {ACTIONS.get(action, action)}", meta={"action": action})

        handler = {
            "pesquisar_fontes": self._act_sources,
            "gerar_sql": self._act_sql,
            "gerar_powershell": self._act_powershell,
            "analisar_log": self._act_log,
            "caso_semelhante": self._act_similar,
            "responder_cliente": self._act_customer,
            "escalonar_n3": self._act_n3,
        }.get(action, self._act_investigate)
        result = handler(case, message)
        msg = cases.add_message(case_id, "assistant", result.content, result.agent, result.sources,
                                {"scripts": [s.as_dict() for s in result.scripts], "action": action, **result.meta})
        return {"message": msg, "case": cases.get_case(case_id)}

    def _act_sources(self, case, message):
        return self.docs.run(message or self.case_query(case))

    def _act_similar(self, case, message):
        return self.similar.run(message or self.case_query(case), case["id"])

    def _act_log(self, case, message):
        text = message or cases.attachment_texts(case["id"], 200_000)
        if not text.strip():
            return AgentResult("LogAnalysisAgent", "Arraste um arquivo de log para o chamado ou cole o conteúdo do log.")
        res = analyze_log(text)
        content = summary_markdown(res)
        llm = self._llm()
        hits = []
        if res["primary_error"]:
            hits = self.docs.search(f"{res['primary_error']['exception']} {res['primary_error']['example']} {case['product']}", 4)
            cases.upsert_fact(case["id"], "Log: erro principal", (res["primary_error"]["exception"] or res["primary_error"]["example"])[:300],
                              "FALHA", source="LogAnalysisAgent")
            if llm:
                try:
                    note = llm.chat([{"role": "system", "content": SYSTEM_BASE},
                                     {"role": "user", "content": f"{self.case_brief(case)}\n\n{source_context(hits)}\n\nRESULTADO DA ANÁLISE DO LOG:\n{content}\n\n"
                                      "Interprete o erro principal e os consequentes para este chamado e diga qual hipótese ele reforça ou descarta."}])
                    content += "\n\n### Interpretação\n" + self.validation.check_answer(note, hits, note)[0]
                except LLMUnavailable:
                    pass
        return AgentResult("LogAnalysisAgent", content, hits, meta={"log": res})

    def _act_powershell(self, case, message):
        focus = f"{self.case_query(case)} {message}"
        modules = pick_modules(focus)
        script = build_diagnostic(modules, target=case["server"], sql_instance=case["database_name"] and case["server"] or "",
                                  title=f"Diagnóstico do chamado {case['number']}")
        content = (f"Gerei um diagnóstico único (somente leitura) cobrindo: **{', '.join(modules)}**.\n\n"
                   "Execute no servidor como administrador e cole aqui o conteúdo de `diagnostico.txt` para eu interpretar.")
        already = cases.memory_text(case["id"])
        if already:
            content += "\n\nTestes já registrados na memória do chamado não precisam ser repetidos:\n```\n" + already + "\n```"
        return AgentResult("PowerShellAgent", content, [], [script])

    def _act_sql(self, case, message):
        hits = self.docs.search(f"{self.case_query(case)} {message}", 6)
        llm = self._llm()
        terms = _terms(f"{case['error_message']} {case['screen']} {case['routine']} {message}") or _terms(case["title"])
        if not llm:
            return AgentResult("SQLAgent", "IA offline: gerei a descoberta de estrutura (somente leitura) a partir dos termos do chamado.",
                               hits, [discovery_script(terms)])
        try:
            data = llm.chat_json([{"role": "system", "content": SQL_SYSTEM},
                                  {"role": "user", "content": f"{self.case_brief(case)}\n\n{source_context(hits)}\n\n"
                                   f"ANEXOS/RESULTADOS:\n{cases.attachment_texts(case['id'])}\n\nOBJETIVO: {message or 'investigar o chamado no banco'}"}])
        except LLMUnavailable as exc:
            return AgentResult("SQLAgent", f"IA indisponível ({exc}). Descoberta de estrutura:", hits, [discovery_script(terms)])
        scripts = self._scripts_from_llm(data, case, hits, message) or [discovery_script(terms)]
        explanation, _ = self.validation.check_answer(data.get("explanation") or "", hits, message or case["title"])
        return AgentResult("SQLAgent", explanation, hits, scripts)

    def _act_customer(self, case, message):
        return CustomerResponseAgent(self._llm()).run(case, message)

    def _act_n3(self, case, message):
        hits = self.docs.search(self.case_query(case), 5)
        result = N3EscalationAgent(self._llm()).run(case, hits)
        if case["status"] != "Escalonado N3":
            cases.update_case(case["id"], {"status": "Escalonado N3"})
        return result

    def _act_investigate(self, case, message):
        query = self.case_query(case, message)
        hits = self.docs.search(query, 6)
        similar = self.similar.run(query, case["id"])
        llm = self._llm()
        if not llm:
            return self._offline_investigation(case, hits, similar)
        attachments = cases.attachment_texts(case["id"])
        user = (f"{self.case_brief(case)}\n\n{source_context(hits)}\n\n"
                + (f"ANEXOS:\n{attachments}\n\n" if attachments else "")
                + (f"CASOS SEMELHANTES (referência, não aplicar sem validar):\n{similar.content}\n\n" if similar.meta.get("similar") else "")
                + (f"NOVA MENSAGEM/RESULTADO DO ANALISTA:\n{message}\n\n" if message else
                   "Inicie a investigação: entenda o problema, levante evidências nas fontes, crie hipóteses e proponha os primeiros testes.\n\n")
                + INVESTIGATION_JSON)
        try:
            data = llm.chat_json([{"role": "system", "content": SYSTEM_BASE}, *self._history(case["id"], 6),
                                  {"role": "user", "content": user}])
        except LLMUnavailable as exc:
            res = self._offline_investigation(case, hits, similar)
            res.content = f"**IA indisponível:** {exc}\n\n" + res.content
            return res
        if not data:
            return self._offline_investigation(case, hits, similar)
        return self._apply_investigation(case, data, hits, message)

    def _apply_investigation(self, case, data, hits, message) -> AgentResult:
        changes: list[str] = []
        for f in data.get("facts") or []:
            if isinstance(f, dict) and f.get("key") and f.get("value"):
                cases.upsert_fact(case["id"], str(f["key"]), str(f["value"]), str(f.get("status") or ""), source="IA")
                changes.append(f"Memória: {f['key']} = {f['value']}")
        existing = {h["title"].lower(): h for h in case["hypotheses"]}
        for raw in data.get("hypotheses") or []:
            if not isinstance(raw, dict) or not raw.get("title"):
                continue
            h = self.validation.sanitize_hypothesis(raw)
            if raw.get("status") != h["status"]:
                changes.append(f"Hipótese '{h['title']}' mantida como {h['status']} (sem evidência para {raw.get('status')})")
            old = existing.get(str(h["title"]).lower())
            try:
                if old:
                    if old["status"] != h["status"]:
                        changes.append(f"Hipótese '{old['title']}': {old['status']} → {h['status']}")
                    cases.update_hypothesis(old["id"], h)
                else:
                    cases.add_hypothesis(case["id"], str(h["title"]), str(h.get("rationale") or ""), str(h.get("test") or ""),
                                         h["status"], str(h.get("evidence") or ""))
            except ValueError:
                continue
        analysis, issues = self.validation.check_answer(str(data.get("analysis") or ""), hits, message or case["title"])
        root = str(data.get("root_cause") or "").strip()
        confirmed = [h for h in cases.get_case(case["id"])["hypotheses"] if h["status"] == "Confirmada"]
        if root and confirmed:
            cases.update_case(case["id"], {"root_cause": root, "resolution": str(data.get("fix") or "")})
        elif root:
            issues.append("Causa raiz sugerida sem hipótese confirmada por evidência: não registrada como confirmada.")
        scripts: list[Script] = []
        nxt = data.get("next_step")
        if nxt == "powershell":
            scripts.append(build_diagnostic(pick_modules(f"{self.case_query(case)} {data.get('powershell_focus', '')}"),
                                            target=case["server"], title=f"Diagnóstico do chamado {case['number']}"))
        elif nxt == "sql":
            goal = str(data.get("sql_goal") or "")
            scripts.append(discovery_script(_terms(goal) or _terms(case["error_message"] or case["title"])))
        content = analysis
        if changes:
            content += "\n\n**Atualizações da investigação:**\n" + "\n".join(f"- {c}" for c in changes)
        return AgentResult("GVSupportOrchestrator", content, hits, scripts, {"validation": issues, "next_step": nxt})

    def _offline_investigation(self, case, hits, similar: AgentResult) -> AgentResult:
        parts = ["**IA offline** — investigação assistida em modo determinístico (fontes + scripts). "
                 "Configure o Ollama para hipóteses e interpretação automática."]
        parts.append(self.docs.run(self.case_query(case)).content if hits else NO_EVIDENCE)
        if similar.meta.get("similar"):
            parts.append("### Casos semelhantes\n" + similar.content)
        scripts = [build_diagnostic(pick_modules(self.case_query(case)), target=case["server"],
                                    title=f"Diagnóstico do chamado {case['number']}")]
        terms = _terms(case["error_message"] or case["title"])
        if terms:
            scripts.append(discovery_script(terms))
        return AgentResult("GVSupportOrchestrator", "\n\n".join(parts), hits, scripts, {"llm": False})


def _terms(text: str) -> list[str]:
    from ..rag import query_terms

    generic = {"erro", "error", "nao", "sistema", "tela", "ao", "gerar", "falha", "problema", "consulta", "sql", "select",
               "tabela", "coluna", "banco", "dados", "qual", "quais", "onde", "fica", "campo"}
    return [t for t in query_terms(text) if t not in generic and len(t) >= 4][:4]


def as_json(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=2)
