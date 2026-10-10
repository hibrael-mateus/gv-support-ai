"""RTMAgent: ReportBuilder reports (.rtm) whose events are written in RAP, ReportBuilder's Pascal.

A .rtm is a Delphi form stream, in text ("object ppReport1: TppReport") or binary ("TPF0") form. The RAP code
is not plain text in either: it sits in TraCodeModule.ProgramStream, a binary property (hex in the text form)
holding one record per event (ProgramName, Source, ComponentName, EventName). describe() turns the file into
readable text (components, data fields, SQL and the code of each event) that the chat shows to the model;
lint() checks the code for the mistakes that break RAP reports most often, with or without a model.
"""
from __future__ import annotations

import re
from typing import Any

from ..llm import LLMProvider, LLMUnavailable, parse_json_loose
from .base import AgentResult, sources_block

PROGRAM_PROPS = {b"ProgramName": "name", b"Source": "source", b"ComponentName": "component", b"EventName": "event"}
SHOWN_PROPS = ("DataPipeline", "DataField", "Caption", "UserName", "DataPipelineName")


# ---- reading the file ---------------------------------------------------------------------------------
def _value(data: bytes, p: int) -> tuple[str | None, int]:
    """One Delphi stream value at p (vaString, vaLString, vaWString, vaUTF8String, vaIdent)."""
    if p >= len(data):
        return None, p
    code = data[p]
    if code in (0x06, 0x07) and p + 1 < len(data):
        n = data[p + 1]
        return data[p + 2:p + 2 + n].decode("cp1252", "replace"), p + 2 + n
    if code in (0x0C, 0x12, 0x14) and p + 5 <= len(data):
        n = int.from_bytes(data[p + 1:p + 5], "little")
        raw = data[p + 5:p + 5 + (n * 2 if code == 0x12 else n)]
        text = raw.decode("utf-16-le" if code == 0x12 else "utf-8" if code == 0x14 else "cp1252", "replace")
        return text, p + 5 + len(raw)
    return None, p + 1


def program_sources(data: bytes) -> list[dict[str, str]]:
    """The RAP events inside a ProgramStream (or a whole binary .rtm, which embeds it)."""
    out: list[dict[str, str]] = []
    cur: dict[str, str] = {}
    i = 0
    while i < len(data) - 2:
        n = data[i]
        name = data[i + 1:i + 1 + n] if 0 < n < 20 else b""
        if name in PROGRAM_PROPS:
            value, j = _value(data, i + 1 + n)
            if value is not None:
                key = PROGRAM_PROPS[name]
                if key == "name" and cur.get("source"):
                    out.append(cur)
                    cur = {}
                cur[key] = value
                i = j
                continue
        i += 1
    if cur.get("source"):
        out.append(cur)
    return out


def _dfm_string(expr: str) -> str:
    """'abc'#13#10'def' → the text it encodes."""
    return "".join(m.group(1).replace("''", "'") if m.group(1) is not None else chr(int(m.group(2)))
                   for m in re.finditer(r"'((?:[^']|'')*)'|#(\d+)", expr))


def parse_rtm(data: bytes) -> dict[str, Any]:
    report: dict[str, Any] = {"name": "", "components": [], "sql": [], "programs": []}
    if data[:4] == b"TPF0":  # binary form: the code records are embedded as raw bytes
        report["programs"] = program_sources(data)
        text = data.decode("cp1252", "replace")
        report["sql"] = [m.group(0) for m in re.finditer(r"(?is)\bSELECT\b[ -~\r\n\t]{10,4000}?\bFROM\b[ -~\r\n\t]{0,2000}", text)][:5]
        return report
    text = data.decode("utf-8-sig", "replace") if data[:3] == b"\xef\xbb\xbf" else data.decode("cp1252", "replace")
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        if m := re.match(r"\s*(?:object|inherited|inline)\s+(\w+)\s*:\s*(\w+)", line):
            report["components"].append({"name": m.group(1), "class": m.group(2)})
            report["name"] = report["name"] or m.group(1)
        elif m := re.match(r"\s*(\w*SQL\w*)\.Strings\s*=\s*\(\s*$", line):
            body = []
            while i + 1 < len(lines) and not lines[i].rstrip().endswith(")"):
                i += 1
                body.append(_dfm_string(lines[i].rstrip().removesuffix(")")))
            pipe = next((c["props"].get("UserName") for c in reversed(report["components"]) if c.get("props", {}).get("UserName")), "")
            report["sql"].append(("-- " + pipe + "\n" if pipe else "") + "\n".join(body))
        elif re.match(r"\s*ProgramStream\s*=\s*\{", line):
            hexes = []
            while i + 1 < len(lines) and "}" not in lines[i]:
                i += 1
                hexes.append(lines[i].replace("}", "").strip())
            try:
                report["programs"] += program_sources(bytes.fromhex("".join(hexes)))
            except ValueError:
                pass
        elif (m := re.match(r"\s*(\w+)\s*=\s*(.+)$", line)) and m.group(1) in SHOWN_PROPS and report["components"]:
            report["components"][-1].setdefault("props", {})[m.group(1)] = _dfm_string(m.group(2)) or m.group(2).strip()
        i += 1
    return report


def describe(name: str, data: bytes) -> str:
    """The readable form of a .rtm the chat hands to the agent (and shows in the conversation)."""
    r = parse_rtm(data)
    parts = [f"[Relatório RTM: {name}]"]
    comps = [c for c in r["components"] if c.get("props")]
    if comps:
        parts.append("COMPONENTES COM DADOS:\n" + "\n".join(
            f"- {c['name']} ({c['class']}) " + " ".join(f"{k}={v}" for k, v in c["props"].items()) for c in comps[:150]))
    for sql in r["sql"]:
        parts.append("SQL:\n" + sql.strip())
    if r["programs"]:
        parts.append("CÓDIGO RAP (aba Calc):\n" + "\n\n".join(
            f"// {p.get('component', '')}.{p.get('event', '')}\n{p['source'].strip()}" for p in r["programs"]))
    else:
        parts.append("CÓDIGO RAP: nenhum evento com código encontrado no arquivo.")
    return "\n\n".join(parts)


# ---- checks -------------------------------------------------------------------------------------------
def _blocks(text: str) -> list[tuple[str, str]]:
    """(name, code) of each procedure/function written in the text."""
    heads = list(re.finditer(r"(?im)^\s*(procedure|function)\s+(\w+)", text))
    return [(h.group(2), text[h.start(): heads[k + 1].start() if k + 1 < len(heads) else len(text)])
            for k, h in enumerate(heads)]


def _strip(code: str) -> str:
    code = re.sub(r"'(?:[^']|'')*'", "''", code)
    return re.sub(r"\{[^}]*\}|\(\*.*?\*\)|//[^\n]*", "", code, flags=re.S)


def known_fields(text: str) -> set[str]:
    fields = {f.upper() for f in re.findall(r"DataField=(\w+)", text)}
    for sql in re.findall(r"(?is)\bSELECT\b(.+?)\bFROM\b", text):
        for col in sql.split(","):
            col = col.strip()
            alias = re.search(r"(?i)\bAS\s+\[?(\w+)\]?\s*$", col) or re.search(r"(\w+)\]?\s*$", col)
            if alias:
                fields.add(alias.group(1).upper())
    return fields


def lint(text: str) -> list[str]:
    """RAP mistakes found without running the report. Text is a describe() output or pasted code."""
    issues: list[str] = []
    fields = known_fields(text)
    for name, raw in _blocks(text):
        code = _strip(raw)
        opens = len(re.findall(r"(?i)\b(begin|case|try)\b", code))
        ends = len(re.findall(r"(?i)\bend\b", code))
        if opens != ends:
            issues.append(f"{name}: {opens} begin/case/try para {ends} end — bloco não fechado.")
        if re.search(r"(?i)^\s*uses\b", code, re.M):
            issues.append(f"{name}: RAP não aceita 'uses'; as funções já estão disponíveis.")
        if re.search(r"(?i)\(\s*var\s+Value\s*:\s*Variant", code) and not re.search(r"(?i)\bValue\s*:=", code):
            issues.append(f"{name}: evento OnCalc sem 'Value := ...'; a variável não recebe valor.")
        for pipe, field in re.findall(r"(\w+)\[\s*'(\w+)'\s*\]", raw):
            if fields and field.upper() not in fields:
                issues.append(f"{name}: campo '{field}' de {pipe} não aparece no SQL nem nos componentes; confira o nome.")
        for div in re.findall(r"/\s*(\w+\[\s*'\w+'\s*\]|\w+\.Value)", raw):
            if not re.search(re.escape(div) + r"\s*(<>|>)\s*0", raw):
                issues.append(f"{name}: divisão por {div} sem testar se é zero (erro 'Division by zero' ao imprimir).")
        if re.search(r"\w+\[\s*'\w+'\s*\]\s*[+\-*/]", raw) and not re.search(r"(?i)VarIsNull|<>\s*null|=\s*null", raw):
            issues.append(f"{name}: conta com campo do banco sem tratar valor nulo (use VarIsNull antes).")
    return list(dict.fromkeys(issues))


# ---- agent --------------------------------------------------------------------------------------------
RTM_SYSTEM = """Você é especialista em relatórios ReportBuilder (.rtm) da GV Dasa e na linguagem RAP (Pascal do ReportBuilder).
Regras da RAP que você deve respeitar:
- Não existe 'uses', classes nem units. Variáveis locais em 'var' dentro do procedimento; globais em Module > Declarations.
- Eventos: TppVariable.OnCalc(var Value: Variant) deve atribuir 'Value := ...'; OnGetText(var Text: String);
  BeforePrint/OnPrint de bandas e componentes; Report.BeforePrint/OnStartPage para inicializações.
- Campos do banco: Pipeline['CAMPO'] ou Pipeline.GetFieldValue('CAMPO'); trate nulos com VarIsNull antes de contas.
- Totais: prefira CalcType/ResetType da TppVariable; somando no OnCalc use 'Value := Value + ...'.
- Funções comuns: Format, FormatFloat, FloatToStr, IntToStr, StrToFloat, DateToStr, FormatDateTime, Copy, Pos, Trim,
  UpperCase, Length, Round, Trunc, VarIsNull.
Nunca invente nomes de campos, pipelines ou componentes: use só os que aparecem no relatório enviado ou nas evidências.
Se faltar informação (ex.: o erro exato), diga qual.
Responda SOMENTE JSON:
{"analysis": "Markdown: o que o relatório faz, a causa provável do problema e por quê (cite [F1] se usar evidências)",
 "fixes": [{"event": "nome do procedimento", "code": "procedimento completo corrigido em RAP"}],
 "steps": "como aplicar no Designer (aba Calc > evento) e como validar"}"""


class RTMAgent:
    name = "RTMAgent"

    def __init__(self, provider: LLMProvider | None):
        self.provider = provider

    def run(self, message: str, hits: list[dict[str, Any]]) -> AgentResult:
        issues = lint(message)
        checks = ("**Verificações automáticas do código:**\n" + "\n".join(f"- {x}" for x in issues)) if issues \
            else "**Verificações automáticas do código:** nenhum problema estrutural encontrado."
        if not self.provider:
            return AgentResult(self.name, "**IA offline**: mostro só as verificações automáticas.\n\n" + checks, hits, meta={"rtm_issues": issues})
        evidence = ("EVIDÊNCIAS GV DASA:\n" + sources_block(hits)) if hits else "EVIDÊNCIAS GV DASA: nenhuma."
        try:
            data = parse_json_loose(self.provider.chat(
                [{"role": "system", "content": RTM_SYSTEM},
                 {"role": "user", "content": f"{evidence}\n\nVERIFICAÇÕES AUTOMÁTICAS:\n{chr(10).join(issues) or 'nenhuma'}\n\n"
                                             f"PEDIDO DO ANALISTA E RELATÓRIO:\n{message}"}], json_mode=True))
        except LLMUnavailable as exc:
            return AgentResult(self.name, f"**IA indisponível:** {exc}\n\n" + checks, hits, meta={"rtm_issues": issues})
        parts = [str(data.get("analysis") or "").strip() or "Analisei o relatório.", checks]
        for fix in data.get("fixes") or []:
            if isinstance(fix, dict) and fix.get("code"):
                parts.append(f"**Código corrigido: {fix.get('event') or 'evento'}**\n```pascal\n{str(fix['code']).strip()}\n```")
        if data.get("steps"):
            parts.append("**Como aplicar:**\n" + str(data["steps"]).strip())
        return AgentResult(self.name, "\n\n".join(parts), hits, meta={"rtm_issues": issues})
