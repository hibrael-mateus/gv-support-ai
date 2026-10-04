"""LogAnalysisAgent: deterministic parsing of logs (IIS, .NET, Event Viewer exports, app logs).

Finds timestamps, servers, processes, errors, exceptions, stack traces and frequency; separates the
primary error (first failure in the timeline) from consequent errors.
"""
from __future__ import annotations

import re
from collections import Counter, OrderedDict
from typing import Any

TS_PATTERNS = [
    re.compile(r"\b(\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:[.,]\d+)?(?:Z|[+-]\d{2}:?\d{2})?)"),
    re.compile(r"\b(\d{2}/\d{2}/\d{4}\s+\d{2}:\d{2}(?::\d{2})?)"),
    re.compile(r"\b(\d{2}-\d{2}-\d{4}\s+\d{2}:\d{2}:\d{2})"),
]
ERROR_RE = re.compile(r"\b(ERROR|ERRO|FATAL|CRITICAL|CRÍTICO|FAIL(?:ED|URE)?|FALHA|EXCEPTION|EXCEÇÃO|EXCECAO)\b|Exception\b|\bHTTP/\d\.\d\"?\s+5\d\d\b|\s5\d\d\s\d+\s\d+\s\d+\s*$", re.I)
WARN_RE = re.compile(r"\b(WARN(?:ING)?|AVISO|ADVERT[EÊ]NCIA)\b", re.I)
EXC_RE = re.compile(r"\b((?:[A-Z][\w]*\.)*[A-Z]\w*(?:Exception|Error))\b")
STACK_RE = re.compile(r"^\s+(at|em)\s+\S+|^\s+File \"|^\s+---\s*(End of|Fim do)", re.I)
SERVER_RE = re.compile(r"\b(?:server|servidor|host|machine|computer|computador)\s*[=:]\s*([\w.\-]+)", re.I)
PROC_RE = re.compile(r"\b(w3wp|sqlservr|dotnet|java|node|svchost|[\w\-]+\.exe)\b(?:\s*\[?(?:pid|PID)[=: ]*(\d+))?", re.I)
NOISE = [(re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.I), "<guid>"),
         (re.compile(r"\b\d+(?:[.,:]\d+)*\b"), "<n>"), (re.compile(r"'[^']*'|\"[^\"]*\""), "<str>")]


def _timestamp(line: str) -> str:
    for p in TS_PATTERNS:
        m = p.search(line)
        if m:
            return m.group(1)
    return ""


def signature(message: str) -> str:
    msg = message
    for pat in TS_PATTERNS:
        msg = pat.sub("", msg)
    for pat, repl in NOISE:
        msg = pat.sub(repl, msg)
    return re.sub(r"\s+", " ", msg).strip()[:180]


def analyze_log(text: str, max_lines: int = 200_000) -> dict[str, Any]:
    lines = text.splitlines()[:max_lines]
    events: list[dict[str, Any]] = []
    servers: Counter = Counter()
    processes: Counter = Counter()
    current: dict[str, Any] | None = None
    last_ts = ""
    for no, line in enumerate(lines, start=1):
        ts = _timestamp(line) or ""
        if ts:
            last_ts = ts
        for m in SERVER_RE.finditer(line):
            servers[m.group(1)] += 1
        for m in PROC_RE.finditer(line):
            processes[m.group(1).lower()] += 1
        if STACK_RE.search(line) and current is not None:
            current["stack"].append(line.strip())
            continue
        level = "error" if ERROR_RE.search(line) else "warning" if WARN_RE.search(line) else ""
        if level:
            exc = EXC_RE.search(line)
            current = {"line": no, "timestamp": ts or last_ts, "level": level, "message": line.strip()[:500],
                       "exception": exc.group(1) if exc else "", "signature": signature(line), "stack": []}
            events.append(current)
        elif ts:
            current = None
        elif current is not None and line.strip() and EXC_RE.search(line) and not current["exception"]:
            current["exception"] = EXC_RE.search(line).group(1)

    errors = [e for e in events if e["level"] == "error"]
    freq = Counter(e["signature"] for e in errors)
    groups: "OrderedDict[str, dict[str, Any]]" = OrderedDict()
    for e in errors:
        g = groups.setdefault(e["signature"], {"signature": e["signature"], "count": 0, "first_line": e["line"],
                                               "first_seen": e["timestamp"], "last_seen": e["timestamp"],
                                               "exception": e["exception"], "example": e["message"],
                                               "stack": e["stack"][:12]})
        g["count"] += 1
        g["last_seen"] = e["timestamp"] or g["last_seen"]
        if not g["stack"] and e["stack"]:
            g["stack"] = e["stack"][:12]

    primary = None
    consequent: list[dict[str, Any]] = []
    if groups:
        ordered = list(groups.values())  # insertion order == first occurrence order
        primary = ordered[0]
        consequent = ordered[1:]
        lo, hi = max(primary["first_line"] - 6, 0), min(primary["first_line"] + 5, len(lines))
        primary["before"] = lines[lo:primary["first_line"] - 1]
        primary["after"] = lines[primary["first_line"]:hi]

    return {
        "total_lines": len(lines),
        "errors": len(errors),
        "warnings": sum(1 for e in events if e["level"] == "warning"),
        "first_timestamp": next((_timestamp(l) for l in lines if _timestamp(l)), ""),
        "last_timestamp": next((_timestamp(l) for l in reversed(lines) if _timestamp(l)), ""),
        "servers": [s for s, _ in servers.most_common(5)],
        "processes": [p for p, _ in processes.most_common(8)],
        "exceptions": Counter(e["exception"] for e in errors if e["exception"]).most_common(10),
        "primary_error": primary,
        "consequent_errors": consequent[:15],
        "frequency": [{"signature": s, "count": c} for s, c in freq.most_common(15)],
    }


def summary_markdown(result: dict[str, Any]) -> str:
    md = [f"**Linhas analisadas:** {result['total_lines']} | **Erros:** {result['errors']} | **Avisos:** {result['warnings']}"]
    if result["first_timestamp"]:
        md.append(f"**Período:** {result['first_timestamp']} → {result['last_timestamp']}")
    if result["servers"]:
        md.append(f"**Servidores:** {', '.join(result['servers'])}")
    if result["processes"]:
        md.append(f"**Processos:** {', '.join(result['processes'])}")
    p = result["primary_error"]
    if p:
        md.append("\n### Erro principal (primeira falha da linha do tempo)")
        md.append(f"- Linha {p['first_line']} | {p['first_seen'] or 'sem horário'} | ocorrências: {p['count']}")
        if p["exception"]:
            md.append(f"- Exceção: `{p['exception']}`")
        md.append(f"```log\n{p['example']}\n```")
        if p.get("stack"):
            md.append("Stack trace:\n```log\n" + "\n".join(p["stack"]) + "\n```")
        if p.get("before"):
            md.append("Eventos anteriores:\n```log\n" + "\n".join(p["before"][-5:]) + "\n```")
    else:
        md.append("\nNenhum erro identificado no log.")
    if result["consequent_errors"]:
        md.append("\n### Erros consequentes / posteriores")
        for g in result["consequent_errors"][:8]:
            md.append(f"- ({g['count']}x, a partir da linha {g['first_line']}) {g['example'][:200]}")
    return "\n".join(md)
