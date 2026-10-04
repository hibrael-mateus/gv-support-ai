"""Case (chamado) persistence and investigation memory."""
from __future__ import annotations

import json
from typing import Any

from .db import connection
from .security import mask_secrets

CASE_FIELDS = ["title", "customer", "product", "module", "routine", "menu", "screen", "error_message",
               "description", "environment", "server", "database_name", "already_validated"]
CASE_STATUSES = ["Em investigação", "Aguardando cliente", "Solucionado", "Escalonado N3", "Cancelado"]
HYPOTHESIS_STATUSES = ["Não validada", "Em análise", "Muito provável", "Confirmada", "Descartada"]
FACT_STATUSES = ["OK", "FALHA", "INFO"]


class EvidenceRequired(ValueError):
    pass


def create_case(data: dict[str, Any]) -> dict[str, Any]:
    values = {f: mask_secrets(str(data.get(f, "") or "")) for f in CASE_FIELDS}
    if not values["title"].strip():
        values["title"] = (values["error_message"] or values["description"] or "Chamado sem título")[:120]
    with connection() as conn:
        cur = conn.execute(
            f"INSERT INTO cases({','.join(CASE_FIELDS)}) VALUES({','.join('?' * len(CASE_FIELDS))})",
            [values[f] for f in CASE_FIELDS],
        )
        case_id = cur.lastrowid
    for line in (values["already_validated"] or "").splitlines():
        if "=" in line:
            key, val = line.split("=", 1)
            upsert_fact(case_id, key.strip(), val.strip(), source="abertura")
    return get_case(case_id)


def update_case(case_id: int, data: dict[str, Any]) -> dict[str, Any]:
    allowed = set(CASE_FIELDS) | {"status", "root_cause", "resolution"}
    sets = {k: mask_secrets(str(v)) for k, v in data.items() if k in allowed and v is not None}
    if "status" in sets and sets["status"] not in CASE_STATUSES:
        raise ValueError(f"Status inválido: {sets['status']}")
    if sets:
        with connection() as conn:
            conn.execute(
                f"UPDATE cases SET {', '.join(f'{k}=?' for k in sets)}, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                [*sets.values(), case_id],
            )
    return get_case(case_id)


def touch(case_id: int) -> None:
    with connection() as conn:
        conn.execute("UPDATE cases SET updated_at=CURRENT_TIMESTAMP WHERE id=?", (case_id,))


def get_case(case_id: int) -> dict[str, Any]:
    with connection() as conn:
        row = conn.execute("SELECT * FROM cases WHERE id=?", (case_id,)).fetchone()
        if not row:
            raise KeyError(case_id)
        case = dict(row)
        case["facts"] = [dict(r) for r in conn.execute("SELECT * FROM facts WHERE case_id=? ORDER BY id", (case_id,))]
        case["hypotheses"] = [dict(r) for r in conn.execute("SELECT * FROM hypotheses WHERE case_id=? ORDER BY id", (case_id,))]
        case["attachments"] = [dict(r) for r in conn.execute(
            "SELECT id,name,size,created_at FROM attachments WHERE case_id=? ORDER BY id", (case_id,))]
    case["number"] = f"#{case_id:06d}"
    return case


def list_cases(status: str = "", query: str = "", limit: int = 200) -> list[dict[str, Any]]:
    sql = "SELECT * FROM cases WHERE 1=1"
    args: list[Any] = []
    if status:
        sql += " AND status=?"
        args.append(status)
    if query:
        sql += " AND (title LIKE ? OR customer LIKE ? OR product LIKE ? OR error_message LIKE ?)"
        args += [f"%{query}%"] * 4
    sql += " ORDER BY updated_at DESC, id DESC LIMIT ?"
    args.append(limit)
    with connection() as conn:
        rows = [dict(r) for r in conn.execute(sql, args)]
    for r in rows:
        r["number"] = f"#{r['id']:06d}"
    return rows


def delete_case(case_id: int) -> None:
    with connection() as conn:
        conn.execute("DELETE FROM cases WHERE id=?", (case_id,))


def upsert_fact(case_id: int, key: str, value: str, status: str = "", source: str = "analista") -> dict[str, Any]:
    value = mask_secrets(value)
    if not status:
        upper = value.upper()
        status = "OK" if upper in {"OK", "RUNNING", "SUCESSO", "TRUE", "ONLINE", "ATIVO"} or upper.startswith("OK") else (
            "FALHA" if any(w in upper for w in ("FALHA", "ERRO", "FAIL", "STOPPED", "TIMEOUT", "NEGADO", "FALSE")) else "INFO")
    if status not in FACT_STATUSES:
        status = "INFO"
    with connection() as conn:
        conn.execute(
            """INSERT INTO facts(case_id,key,value,status,source) VALUES(?,?,?,?,?)
               ON CONFLICT(case_id,key) DO UPDATE SET value=excluded.value, status=excluded.status,
               source=excluded.source, created_at=CURRENT_TIMESTAMP""",
            (case_id, key.strip()[:200], value.strip()[:2000], status, source),
        )
        row = conn.execute("SELECT * FROM facts WHERE case_id=? AND key=?", (case_id, key.strip()[:200])).fetchone()
    touch(case_id)
    return dict(row)


def delete_fact(fact_id: int) -> None:
    with connection() as conn:
        conn.execute("DELETE FROM facts WHERE id=?", (fact_id,))


def memory_text(case_id: int) -> str:
    """The case memory as compact lines for the LLM: tests already done must not be requested again."""
    with connection() as conn:
        facts = conn.execute("SELECT key,value,status FROM facts WHERE case_id=? ORDER BY id", (case_id,)).fetchall()
    return "\n".join(f"{f['key']} = {f['value']} [{f['status']}]" for f in facts)


def add_hypothesis(case_id: int, title: str, rationale: str = "", test: str = "", status: str = "Não validada",
                   evidence: str = "") -> dict[str, Any]:
    _check_hypothesis(status, evidence)
    with connection() as conn:
        existing = conn.execute("SELECT id FROM hypotheses WHERE case_id=? AND lower(title)=lower(?)",
                                (case_id, title.strip())).fetchone()
        if existing:
            return update_hypothesis(existing["id"], {"rationale": rationale, "test": test})
        cur = conn.execute(
            "INSERT INTO hypotheses(case_id,title,rationale,test,status,evidence) VALUES(?,?,?,?,?,?)",
            (case_id, title.strip()[:300], rationale, test, status, evidence),
        )
        row = conn.execute("SELECT * FROM hypotheses WHERE id=?", (cur.lastrowid,)).fetchone()
    touch(case_id)
    return dict(row)


def _check_hypothesis(status: str, evidence: str) -> None:
    if status not in HYPOTHESIS_STATUSES:
        raise ValueError(f"Status de hipótese inválido: {status}")
    if status in ("Confirmada", "Descartada") and not (evidence or "").strip():
        raise EvidenceRequired(f"Uma hipótese só pode ser marcada como '{status}' com evidência registrada.")


def update_hypothesis(hyp_id: int, data: dict[str, Any]) -> dict[str, Any]:
    with connection() as conn:
        row = conn.execute("SELECT * FROM hypotheses WHERE id=?", (hyp_id,)).fetchone()
        if not row:
            raise KeyError(hyp_id)
        current = dict(row)
        merged = {**current, **{k: v for k, v in data.items() if k in ("title", "rationale", "test", "status", "evidence") and v not in (None, "")}}
        _check_hypothesis(merged["status"], merged["evidence"])
        conn.execute(
            "UPDATE hypotheses SET title=?, rationale=?, test=?, status=?, evidence=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (merged["title"], merged["rationale"], merged["test"], merged["status"], mask_secrets(merged["evidence"]), hyp_id),
        )
        row = conn.execute("SELECT * FROM hypotheses WHERE id=?", (hyp_id,)).fetchone()
    touch(current["case_id"])
    return dict(row)


def add_message(case_id: int | None, role: str, content: str, agent: str = "", sources: list | None = None,
                meta: dict | None = None) -> dict[str, Any]:
    with connection() as conn:
        cur = conn.execute(
            "INSERT INTO messages(case_id,role,content,agent,sources_json,meta_json) VALUES(?,?,?,?,?,?)",
            (case_id, role, mask_secrets(content), agent, json.dumps(sources or [], ensure_ascii=False),
             json.dumps(meta or {}, ensure_ascii=False)),
        )
        row = conn.execute("SELECT * FROM messages WHERE id=?", (cur.lastrowid,)).fetchone()
    if case_id:
        touch(case_id)
    return _message(row)


def _message(row) -> dict[str, Any]:
    msg = dict(row)
    msg["sources"] = json.loads(msg.pop("sources_json") or "[]")
    msg["meta"] = json.loads(msg.pop("meta_json") or "{}")
    return msg


def list_messages(case_id: int | None, limit: int = 200) -> list[dict[str, Any]]:
    with connection() as conn:
        if case_id is None:
            rows = conn.execute("SELECT * FROM messages WHERE case_id IS NULL ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        else:
            rows = conn.execute("SELECT * FROM messages WHERE case_id=? ORDER BY id DESC LIMIT ?", (case_id, limit)).fetchall()
    return [_message(r) for r in reversed(rows)]


def clear_free_chat() -> None:
    with connection() as conn:
        conn.execute("DELETE FROM messages WHERE case_id IS NULL")


def add_attachment(case_id: int | None, name: str, path: str, size: int, excerpt: str) -> dict[str, Any]:
    with connection() as conn:
        cur = conn.execute("INSERT INTO attachments(case_id,name,path,size,text_excerpt) VALUES(?,?,?,?,?)",
                           (case_id, name, path, size, mask_secrets(excerpt[:20000])))
        row = conn.execute("SELECT id,case_id,name,size,created_at FROM attachments WHERE id=?", (cur.lastrowid,)).fetchone()
    return dict(row)


def attachment_texts(case_id: int, limit_chars: int = 6000) -> str:
    with connection() as conn:
        rows = conn.execute("SELECT name,text_excerpt FROM attachments WHERE case_id=? ORDER BY id DESC", (case_id,)).fetchall()
    out, used = [], 0
    for r in rows:
        piece = f"[Anexo: {r['name']}]\n{r['text_excerpt'][:2000]}"
        if used + len(piece) > limit_chars:
            break
        out.append(piece)
        used += len(piece)
    return "\n\n".join(out)


def add_feedback(message_id: int, useful: bool, reason: str = "", comment: str = "") -> dict[str, Any]:
    with connection() as conn:
        cur = conn.execute("INSERT INTO feedback(message_id,useful,reason,comment) VALUES(?,?,?,?)",
                           (message_id, int(useful), reason, comment))
        row = conn.execute("SELECT * FROM feedback WHERE id=?", (cur.lastrowid,)).fetchone()
    return dict(row)


def dashboard() -> dict[str, Any]:
    with connection() as conn:
        def count(where: str = "1=1", *args) -> int:
            return conn.execute(f"SELECT COUNT(*) FROM cases WHERE {where}", args).fetchone()[0]

        data = {
            "investigated": count(),
            "in_progress": count("status IN ('Em investigação','Aguardando cliente')"),
            "solved": count("status='Solucionado'"),
            "escalated": count("status='Escalonado N3'"),
            "recent_cases": [dict(r) for r in conn.execute(
                "SELECT id,title,customer,product,status,updated_at FROM cases ORDER BY created_at DESC, id DESC LIMIT 6")],
            "recent_investigations": [dict(r) for r in conn.execute(
                """SELECT c.id, c.title, c.status, m.content AS last_message, m.created_at
                   FROM messages m JOIN cases c ON c.id=m.case_id
                   WHERE m.id IN (SELECT MAX(id) FROM messages WHERE case_id IS NOT NULL GROUP BY case_id)
                   ORDER BY m.id DESC LIMIT 6""")],
        }
    for key in ("recent_cases", "recent_investigations"):
        for r in data[key]:
            r["number"] = f"#{r['id']:06d}"
    return data


def similar_local_cases(text: str, exclude_id: int | None = None, limit: int = 5) -> list[dict[str, Any]]:
    """Resolved cases in the local history that share terms with the current problem."""
    from .rag import normalize, query_terms

    terms = query_terms(text)[:12]
    if not terms:
        return []
    with connection() as conn:
        rows = [dict(r) for r in conn.execute(
            "SELECT id,title,product,module,error_message,description,root_cause,resolution,status FROM cases "
            "WHERE status IN ('Solucionado','Escalonado N3') AND id != ?", (exclude_id or -1,))]
    scored = []
    for r in rows:
        hay = normalize(" ".join(str(r[k] or "") for k in ("title", "product", "module", "error_message", "description", "root_cause")))
        score = sum(1 for t in terms if t in hay) / len(terms)
        if score >= 0.25:
            scored.append({**r, "similarity": round(score * 100), "number": f"#{r['id']:06d}"})
    return sorted(scored, key=lambda x: -x["similarity"])[:limit]
