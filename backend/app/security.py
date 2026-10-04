"""Security rules enforced in code (not only in prompts).

1. Knowledge-source scope: a Drive item may enter the RAG only if the authorized folder
   is one of its ancestors.
2. Secret masking for logs, chat history exports and backups.
3. Danger classification of generated SQL / PowerShell.
"""
from __future__ import annotations

import logging
import re
from collections.abc import Callable
from dataclasses import dataclass

from .settings import ALLOWED_GOOGLE_DRIVE_FOLDER_ID

ACCEPTED_SOURCE = "ACCEPTED_SOURCE"
REJECTED_SOURCE = "REJECTED_SOURCE"


class SourceRejectedError(PermissionError):
    pass


def is_allowed_by_ancestry(
    file_id: str,
    parents_lookup: Callable[[str], list[str]],
    allowed_folder_id: str = ALLOWED_GOOGLE_DRIVE_FOLDER_ID,
    max_depth: int = 64,
) -> bool:
    """Walk the parent graph (Drive items may have several parents) looking for the allowed folder."""
    if file_id == allowed_folder_id:
        return True
    seen: set[str] = set()
    frontier = [file_id]
    for _ in range(max_depth):
        if not frontier:
            break
        nxt: list[str] = []
        for current in frontier:
            if current in seen:
                continue
            seen.add(current)
            for parent in parents_lookup(current) or []:
                if parent == allowed_folder_id:
                    return True
                if parent not in seen:
                    nxt.append(parent)
        frontier = nxt
    return False


def classify_source(
    file_id: str,
    parents_lookup: Callable[[str], list[str]],
    allowed_folder_id: str = ALLOWED_GOOGLE_DRIVE_FOLDER_ID,
) -> str:
    try:
        ok = is_allowed_by_ancestry(file_id, parents_lookup, allowed_folder_id)
    except Exception:
        ok = False  # fail closed: lookup errors never let a file in
    return ACCEPTED_SOURCE if ok else REJECTED_SOURCE


def enforce_allowed_source(
    file_id: str,
    parents_lookup: Callable[[str], list[str]],
    allowed_folder_id: str = ALLOWED_GOOGLE_DRIVE_FOLDER_ID,
) -> None:
    if classify_source(file_id, parents_lookup, allowed_folder_id) != ACCEPTED_SOURCE:
        raise SourceRejectedError(f"{REJECTED_SOURCE}: {file_id} não pertence à pasta autorizada.")


# ---- secret masking ------------------------------------------------------
_MASK_PATTERNS = [
    # key=value / key: value pairs (connection strings, configs, headers)
    re.compile(
        r"(?i)\b(password|passwd|pwd|senha|token|access_token|refresh_token|api[_-]?key|apikey|secret|client_secret|cookie|set-cookie)\b(\s*[=:]\s*)(\"[^\"]*\"|'[^']*'|[^\s;,&]+)"
    ),
    re.compile(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9\-._~+/]+=*"),
    re.compile(r"\bsk-[A-Za-z0-9_\-]{16,}\b"),  # OpenAI-style keys
    re.compile(r"\bgsk_[A-Za-z0-9]{20,}\b"),  # Groq keys
    re.compile(r"\bAIza[0-9A-Za-z_\-]{30,}\b"),  # Google API keys
    re.compile(r"\bAQ\.[0-9A-Za-z_\-]{20,}"),  # Google AI Studio keys (newer format)
    re.compile(r"(?<=[?&])(?:key|api_key|token|access_token|sig|signature)=[^&\s'\"]+"),  # secrets in URLs
    re.compile(r"\bya29\.[0-9A-Za-z_\-]+"),  # Google OAuth access tokens
]


def mask_secrets(text: str) -> str:
    if not text:
        return text
    out = _MASK_PATTERNS[0].sub(lambda m: f"{m.group(1)}{m.group(2)}********", text)
    out = _MASK_PATTERNS[1].sub(lambda m: f"{m.group(1)} ********", out)
    for pattern in _MASK_PATTERNS[2:]:
        out = pattern.sub("********", out)
    return out


class SecretMaskingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = mask_secrets(str(record.getMessage()))
        record.args = ()
        return True


# ---- danger classification -----------------------------------------------
@dataclass
class DangerReport:
    dangerous: bool
    reasons: list[str]

    def as_dict(self) -> dict:
        return {"dangerous": self.dangerous, "reasons": self.reasons}


_SQL_DANGER = [
    (r"\bDELETE\b", "DELETE remove registros"),
    (r"\bUPDATE\b", "UPDATE altera registros"),
    (r"\bDROP\b", "DROP remove objetos"),
    (r"\bTRUNCATE\b", "TRUNCATE apaga todos os registros"),
    (r"\bALTER\b", "ALTER altera estrutura"),
    (r"\bMERGE\b", "MERGE altera registros"),
    (r"\bINSERT\b", "INSERT inclui registros"),
    (r"\bEXEC(UTE)?\b", "EXEC executa procedure com efeito desconhecido"),
    (r"\bGRANT\b|\bREVOKE\b|\bDENY\b", "altera permissões"),
    (r"\bSHUTDOWN\b|\bKILL\b", "interrompe o servidor ou sessões"),
]

_PS_DANGER = [
    (r"\bRemove-Item\b|\brm\s|\bdel\s|\brmdir\b", "remove arquivos ou pastas"),
    (r"\bStop-Service\b", "para serviço"),
    (r"\bRestart-Service\b", "reinicia serviço"),
    (r"\bStop-Process\b|\bkill\b", "encerra processo"),
    (r"\bRestart-Computer\b|\bStop-Computer\b", "reinicia/desliga o servidor"),
    (r"\bSet-\w+|\bNew-\w+|\bAdd-\w+|\bClear-\w+|\bDisable-\w+|\bEnable-\w+|\bUninstall-\w+|\bInstall-\w+", "altera configuração do sistema"),
    (r"\bInvoke-Sqlcmd\b[^\n]*\b(UPDATE|DELETE|DROP|ALTER|TRUNCATE)\b", "altera banco de dados"),
    (r"\bFormat-Volume\b|\bInitialize-Disk\b", "formata disco"),
    (r"\bReset-\w+|\bRestart-WebAppPool\b|\bStop-WebAppPool\b|\bStop-Website\b", "interrompe IIS"),
]

_STRIP_SQL_COMMENTS = re.compile(r"--[^\n]*|/\*.*?\*/", re.S)
_STRIP_SQL_STRINGS = re.compile(r"'(?:''|[^'])*'")
_STRIP_PS_COMMENTS = re.compile(r"#[^\n]*|<#.*?#>", re.S)
_STRIP_PS_STRINGS = re.compile(r"\"(?:`.|[^\"])*\"|'(?:''|[^'])*'")
# Export cmdlets that the diagnostic script itself uses to write its report are harmless.
_PS_SAFE_WRITERS = re.compile(r"\b(New-Item\s+-ItemType\s+Directory|Set-Location|Set-StrictMode|Add-Content|New-Object)\b", re.I)


def classify_sql(sql: str) -> DangerReport:
    body = _STRIP_SQL_STRINGS.sub("''", _STRIP_SQL_COMMENTS.sub(" ", sql or ""))
    reasons = [why for pat, why in _SQL_DANGER if re.search(pat, body, re.I)]
    return DangerReport(bool(reasons), reasons)


def classify_powershell(script: str) -> DangerReport:
    body = _STRIP_PS_STRINGS.sub("''", _STRIP_PS_COMMENTS.sub(" ", script or ""))
    body = _PS_SAFE_WRITERS.sub(" ", body)
    reasons = sorted({why for pat, why in _PS_DANGER if re.search(pat, body, re.I)})
    return DangerReport(bool(reasons), reasons)
