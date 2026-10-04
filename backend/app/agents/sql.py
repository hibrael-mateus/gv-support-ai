"""SQLAgent: SQL Server investigation. DESCOBRIR → SELECT → ANALISAR → ALTERAR → VALIDAR.

Code-level guarantees (independent of the LLM):
* discovery scripts only touch catalog views (INFORMATION_SCHEMA / sys.*);
* any table referenced by generated SQL that does not appear in the evidence / case memory
  is flagged as "objeto não confirmado" and discovery queries are attached;
* changes are always wrapped in a transaction with COMMIT commented out.
"""
from __future__ import annotations

import re

from ..rag import normalize
from ..security import classify_sql
from .base import ANTI_HALLUCINATION, Script

SYSTEM_SCHEMAS = ("sys.", "information_schema.", "msdb.", "master.", "tempdb.")


def _lit(term: str) -> str:
    return term.replace("'", "''").replace("[", "[[]").replace("%", "[%]").replace("_", "[_]")


def discovery_script(terms: list[str] | str) -> Script:
    if isinstance(terms, str):
        terms = [t for t in re.split(r"[\s,;]+", terms) if t]
    terms = [t for t in terms if len(t) >= 3][:5] or ["termo"]
    like_cols = "\n   OR ".join(f"c.COLUMN_NAME LIKE '%{_lit(t)}%' OR c.TABLE_NAME LIKE '%{_lit(t)}%'" for t in terms)
    like_obj = "\n   OR ".join(f"o.name LIKE '%{_lit(t)}%'" for t in terms)
    like_def = "\n   OR ".join(f"m.definition LIKE '%{_lit(t)}%'" for t in terms)
    like_tab = "\n   OR ".join(f"t.name LIKE '%{_lit(t)}%'" for t in terms)
    code = f"""-- GV Support AI | SQLAgent | DESCOBERTA (somente leitura)
-- Termos: {', '.join(terms)}
-- Nenhuma estrutura GV Dasa é presumida: descubra antes de consultar dados.

-- 1) Tabelas e colunas relacionadas
SELECT c.TABLE_SCHEMA, c.TABLE_NAME, c.COLUMN_NAME, c.DATA_TYPE, c.CHARACTER_MAXIMUM_LENGTH, c.IS_NULLABLE
FROM INFORMATION_SCHEMA.COLUMNS c
WHERE {like_cols}
ORDER BY c.TABLE_NAME, c.ORDINAL_POSITION;

-- 2) Objetos (tabelas, views, procedures, funções, triggers)
SELECT s.name AS schema_name, o.name AS object_name, o.type_desc, o.create_date, o.modify_date
FROM sys.objects o
JOIN sys.schemas s ON s.schema_id = o.schema_id
WHERE {like_obj}
ORDER BY o.type_desc, o.name;

-- 3) Procedures, views, funções e triggers que mencionam os termos
SELECT OBJECT_SCHEMA_NAME(m.object_id) AS schema_name, OBJECT_NAME(m.object_id) AS object_name,
       o.type_desc
FROM sys.sql_modules m
JOIN sys.objects o ON o.object_id = m.object_id
WHERE {like_def}
ORDER BY o.type_desc, object_name;

-- 4) Relacionamentos (chaves estrangeiras) das tabelas encontradas
SELECT fk.name AS fk_name,
       OBJECT_SCHEMA_NAME(fk.parent_object_id) + '.' + OBJECT_NAME(fk.parent_object_id) AS tabela_filha,
       COL_NAME(fkc.parent_object_id, fkc.parent_column_id) AS coluna_filha,
       OBJECT_SCHEMA_NAME(fk.referenced_object_id) + '.' + OBJECT_NAME(fk.referenced_object_id) AS tabela_pai,
       COL_NAME(fkc.referenced_object_id, fkc.referenced_column_id) AS coluna_pai
FROM sys.foreign_keys fk
JOIN sys.foreign_key_columns fkc ON fkc.constraint_object_id = fk.object_id
JOIN sys.tables t ON t.object_id IN (fk.parent_object_id, fk.referenced_object_id)
WHERE {like_tab}
ORDER BY tabela_filha;

-- 5) Volume das tabelas encontradas
SELECT s.name AS schema_name, t.name AS table_name, SUM(p.rows) AS row_count
FROM sys.tables t
JOIN sys.schemas s ON s.schema_id = t.schema_id
JOIN sys.partitions p ON p.object_id = t.object_id AND p.index_id IN (0, 1)
WHERE {like_tab}
GROUP BY s.name, t.name
ORDER BY row_count DESC;

-- 6) Triggers das tabelas encontradas (podem alterar o comportamento esperado)
SELECT OBJECT_NAME(tr.parent_id) AS tabela, tr.name AS trigger_name, tr.is_disabled
FROM sys.triggers tr
JOIN sys.tables t ON t.object_id = tr.parent_id
WHERE {like_tab};
"""
    return Script("sql", "Descoberta de estrutura (somente leitura)", code)


def correction_script(table: str, where: str, set_clause: str = "", delete: bool = False) -> Script:
    """Four-step safe change for a structure the analyst has already confirmed."""
    action = (f"DELETE FROM {table}\nWHERE {where};" if delete else f"UPDATE {table}\nSET {set_clause}\nWHERE {where};")
    code = f"""-- GV Support AI | SQLAgent | CORREÇÃO EM 4 ETAPAS
-- ATENÇÃO: script de ALTERAÇÃO. Revise, execute primeiro em homologação e valide com o cliente.

-- 1) SELECT de diagnóstico
SELECT COUNT(*) AS registros_afetados
FROM {table}
WHERE {where};

-- 2) SELECT dos registros afetados (guarde este resultado como evidência/backup)
SELECT *
FROM {table}
WHERE {where};

-- 3) Alteração em transação
SET XACT_ABORT ON;
BEGIN TRANSACTION;

{action}

SELECT @@ROWCOUNT AS linhas_alteradas;  -- deve ser igual ao total da etapa 1

-- 4) SELECT de validação (antes de confirmar)
SELECT *
FROM {table}
WHERE {where};

-- Confira o resultado e escolha UMA das linhas abaixo:
-- COMMIT;
-- ROLLBACK;
"""
    danger = classify_sql(code)
    return Script("sql", "Correção com transação", code, danger.dangerous, danger.reasons)


_TABLE_REF = re.compile(r"\b(?:FROM|JOIN|UPDATE|INTO|TABLE)\s+((?:\[?[\w$#]+\]?\.){0,2}\[?[\w$#]+\]?)", re.I)


def referenced_tables(sql: str) -> list[str]:
    body = re.sub(r"--[^\n]*|/\*.*?\*/", " ", sql, flags=re.S)
    names = []
    for m in _TABLE_REF.finditer(body):
        name = m.group(1).replace("[", "").replace("]", "")
        if name.upper() in {"SELECT", "TRANSACTION", "TRAN"} or name.startswith(("@", "#")):
            continue
        names.append(name)
    return list(dict.fromkeys(names))


def unconfirmed_objects(sql: str, known_text: str) -> list[str]:
    known = normalize(known_text)
    out = []
    for name in referenced_tables(sql):
        lowered = name.lower()
        if lowered.startswith(SYSTEM_SCHEMAS) or lowered.startswith("information_schema"):
            continue
        if normalize(name.split(".")[-1]) not in known:
            out.append(name)
    return out


def guard_sql(code: str, known_text: str, title: str = "SQL gerado") -> list[Script]:
    """Classify danger, flag invented objects, enforce transaction wrapping."""
    danger = classify_sql(code)
    warnings = []
    missing = unconfirmed_objects(code, known_text)
    scripts: list[Script] = []
    if missing:
        warnings.append("Objetos não confirmados nas fontes/evidências: " + ", ".join(missing)
                        + ". Execute a descoberta antes de usar este script.")
    if danger.dangerous and not re.search(r"BEGIN\s+TRAN", code, re.I):
        code = ("-- GV Support AI: alteração envolvida em transação automaticamente\nSET XACT_ABORT ON;\nBEGIN TRANSACTION;\n\n"
                + code.rstrip() + "\n\n-- Valide com SELECT antes de confirmar:\n-- COMMIT;\n-- ROLLBACK;\n")
    scripts.append(Script("sql", title, code, danger.dangerous, danger.reasons, warnings))
    if missing:
        scripts.insert(0, discovery_script([n.split(".")[-1] for n in missing]))
    return scripts


SQL_SYSTEM = (
    "Você é o SQLAgent do GV Support AI, especialista em investigação de SQL Server.\n" + ANTI_HALLUCINATION + "\n"
    "Formato da resposta: JSON {\"explanation\": markdown, \"scripts\": [{\"title\": str, \"sql\": str}]}. "
    "Ordem: descoberta (se estrutura não confirmada) → SELECT diagnóstico → SELECT afetados → alteração em "
    "BEGIN TRANSACTION com COMMIT/ROLLBACK comentados → SELECT de validação."
)
