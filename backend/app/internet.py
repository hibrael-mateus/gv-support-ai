"""Auxiliary internet search, limited to official Microsoft documentation for external technologies.

GV Dasa internals (tables, columns, procedures, screens, rules) are NEVER searched online:
those questions are refused here and must be answered from the authorized Drive folder only.
"""
from __future__ import annotations

import re

import httpx

from .rag import normalize

GV_INTERNAL = re.compile(
    r"\b(gv\w*|gvdasa|gv dasa|portal (do )?(professor|aluno)|pergamum|edumessenger|tabela|coluna|procedure|"
    r"proc\b|trigger|view|parametro|parâmetro|tela|rotina|menu)\b",
    re.I,
)
ALLOWED_HOSTS = ("learn.microsoft.com", "docs.microsoft.com", "support.microsoft.com", "techcommunity.microsoft.com")


def is_allowed_query(query: str) -> bool:
    return not GV_INTERNAL.search(normalize(query))


def search_microsoft_learn(query: str, limit: int = 5) -> list[dict]:
    if not is_allowed_query(query):
        return []
    try:
        r = httpx.get("https://learn.microsoft.com/api/search",
                      params={"search": query, "locale": "pt-br", "$top": limit}, timeout=8)
        r.raise_for_status()
    except httpx.HTTPError:
        return []
    out = []
    for item in r.json().get("results", [])[:limit]:
        url = item.get("url", "")
        if any(h in url for h in ALLOWED_HOSTS):
            out.append({"title": item.get("title", ""), "url": url, "description": item.get("description", "")})
    return out
