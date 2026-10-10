"""Text extraction, chunking and metadata inference for knowledge sources and attachments."""
from __future__ import annotations

import csv
import html
import io
import re
import zipfile
from pathlib import PurePath

TEXT_EXT = {".txt", ".md", ".log", ".sql", ".ps1", ".psm1", ".xml", ".json", ".csv", ".ini", ".config",
            ".cs", ".js", ".ts", ".html", ".htm", ".bat", ".cmd", ".yaml", ".yml", ".rtm", ".tsv"}

KNOWN_PRODUCTS = ["GVcollege PRO", "GVcollege", "GVmobile", "GVcentris", "GVerp", "GVsign", "GVquest",
                  "Portal do Professor", "Portal Professor", "Portal do Aluno", "Pergamum", "EDUmessenger",
                  "Gestão de Contratos", "GVnfse", "GVpay", "Gibbe", "GVmail", "SaaS", "Serviços"]

DOC_TYPES = [
    (r"\bKI\s*\d+|\bKI\b", "KI"),
    (r"\bRTM\b", "RTM"),
    (r"\bFAQ\b|perguntas frequentes", "FAQ"),
    (r"\bmanual\b|guia|tutorial|passo a passo", "Manual"),
    (r"\bscript\b|\.sql$|\.ps1$", "Script"),
    (r"\bchamado\b|\bticket\b|\bcaso\b|registro", "Chamado"),
    (r"procedimento|\bPOP\b|\bprocesso\b", "Procedimento"),
]


def decode_bytes(data: bytes) -> str:
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def extract_pages(name: str, data: bytes, mime: str = "") -> list[tuple[int, str]]:
    """Return [(page_number, text)]. Page is 1-based for paginated formats, 0 otherwise."""
    ext = PurePath(name).suffix.lower()
    if ext == ".pdf" or mime == "application/pdf":
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(data))
        return [(i + 1, page.extract_text() or "") for i, page in enumerate(reader.pages)]
    if ext == ".docx" or "wordprocessingml" in mime:
        import docx

        doc = docx.Document(io.BytesIO(data))
        parts = [p.text for p in doc.paragraphs]
        for table in doc.tables:
            for row in table.rows:
                parts.append(" | ".join(cell.text.strip() for cell in row.cells))
        return [(0, "\n".join(parts))]
    if ext in (".xlsx", ".xlsm") or "spreadsheetml" in mime:
        import openpyxl

        wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        pages = []
        for idx, ws in enumerate(wb.worksheets, start=1):
            rows = []
            for row in ws.iter_rows(values_only=True):
                if any(v is not None for v in row):
                    rows.append(" | ".join("" if v is None else str(v) for v in row))
            pages.append((idx, f"[Planilha: {ws.title}]\n" + "\n".join(rows)))
        return pages
    if ext == ".zip" or mime == "application/zip":
        pages = []
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            for info in zf.infolist()[:200]:
                if info.is_dir() or info.file_size > 20_000_000:
                    continue
                inner_ext = PurePath(info.filename).suffix.lower()
                if inner_ext in TEXT_EXT | {".pdf", ".docx", ".xlsx"}:
                    for _, text in extract_pages(info.filename, zf.read(info), ""):
                        pages.append((0, f"[{info.filename}]\n{text}"))
        return pages
    if ext == ".rtm":  # ReportBuilder: components, SQL and the RAP code hidden in a binary property
        from .agents.rtm import describe

        return [(0, describe(name, data))]
    if ext == ".csv" or ext == ".tsv" or mime == "text/csv":
        text = decode_bytes(data)
        reader = csv.reader(io.StringIO(text), delimiter="\t" if ext == ".tsv" else ",")
        return [(0, "\n".join(" | ".join(r) for r in reader))]
    if ext in TEXT_EXT or mime.startswith("text/") or not ext:
        text = decode_bytes(data)
        return split_package(text) if is_package(text) else [(0, text)]
    raise ValueError(f"Formato não suportado para extração de texto: {ext or mime}")


# ---- "AI-READY-PACKAGE" markdown (TOPdesk KIs and closed tickets exported to the Drive folder) ----------
# Each file bundles several original sources ("## Fonte: X.md") and each source holds many KIs ("### title")
# or tickets ("#### Solicitação do cliente"). Indexing them as one blob makes citations useless ("p53.md"),
# so every KI / ticket becomes its own section with a readable title.
_FONTE = re.compile(r"^#{2} Fonte:\s*(.+?)\s*$", re.M)
_FIM = re.compile(r"^\(Fim da fonte:.*$", re.M)
_TICKET = re.compile(r"(?:^|-{3})\s*#{2,4} Solicitação do cliente\s*$", re.M)  # older TOPdesk ticket export
_FAQ_TICKET = re.compile(r"^\*\*Chamado:\*\*\s*(\S+)", re.M)  # FAQ export: "**Chamado:** 2609-1466" then "## question"
_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*$", re.M)
_COLLECTION = re.compile(r"^\s*#\s+(Coleção de KIs|Perguntas frequentes)\b", re.I)
_NOISE = re.compile(
    r"lembrete de retorno|estamos aguardando seu retorno|avali(e|ar) (este|o meu|meu) atendimento|sua opinião (é|nos)"
    r"|alerta \d+h|data alvo do slo|lançar as horas|digitask|podemos encerrar|chamado encerrado|vence em \d+h"
    r"|^\W*link topdesk:|^\W*módulo:\W*não informado", re.I)
_PLACEHOLDER = ("Sem conteúdo", "Sem descrição")


def is_package(text: str) -> bool:
    """AI-READY packages and the standalone TOPdesk collections/FAQs they are built from."""
    return "AI-READY-PACKAGE" in text[:500] or bool(_FONTE.search(text[:20000])) or bool(_COLLECTION.match(text[:300]))


def clean_markup(text: str) -> str:
    text = html.unescape(html.unescape(text.replace("\\&", "&")))
    text = re.sub(r"<img[^>]*>", "", text, flags=re.I)
    text = re.sub(r"<a\s[^>]*>(.*?)</a>", r"\1", text, flags=re.I | re.S)
    text = re.sub(r"</?(u|b|i|ul|li|br|p|span|div|strong|em)[^>]*>", " ", text, flags=re.I)
    text = re.sub(r"https?://\S*[?&](session|cs|token|sig|code)=\S+", "[link removido]", text, flags=re.I)
    lines = [ln.rstrip() for ln in text.splitlines() if not _NOISE.search(ln)]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def _source_meta(fonte: str) -> dict[str, str]:
    base = re.sub(r"\s*\(trecho.*$", "", fonte).removesuffix(".md")
    up = normalize_upper(base)
    kind = "Chamado" if up.startswith(("FAQ_CHAMADOS", "PERGUNTAS FREQUENTES")) else \
        "KI" if "KIS" in up or "COLECAO" in up else ""
    product = re.sub(r"^(FAQ_CHAMADOS|COLECAO_KIS_E_MANUAIS|COLECAO_KIS)_*|^(Coleção de KIs|Perguntas frequentes)\s*[—–-]\s*",
                     "", base, flags=re.I).replace("_", " ").strip()
    return {"fonte": base + ".md", "product": product, "doc_type": kind}


def normalize_upper(text: str) -> str:
    import unicodedata

    return "".join(c for c in unicodedata.normalize("NFKD", text.upper()) if not unicodedata.combining(c))


def _ticket_items(body: str, product: str) -> list[tuple[str, str]]:
    if _FAQ_TICKET.search(body):
        marks = list(_FAQ_TICKET.finditer(body))
        items = []
        for i, m in enumerate(marks):
            part = body[m.start(): marks[i + 1].start() if i + 1 < len(marks) else len(body)]
            head = _HEADING.search(part)
            question = head.group(2) if head else clean_markup(part[m.end():]).split("\n")[0]
            items.append((f"Chamado {m.group(1)} ({product}): {question[:140]}", part))
        return items
    items = []
    for part in _TICKET.split(body)[1:]:
        request = clean_markup(part.split("Histórico técnico")[0]).lstrip("- ").strip()
        first = re.sub(r"\s+", " ", re.sub(r"^\d{2}/\d{2}/\d{4}\s+\d{2}:\d{2}\s*\[[^\]]*\][^:]*:\s*", "", request))
        first = re.sub(r"^(bom dia|boa tarde|boa noite|olá|prezados)[,!.]?\s*(tudo bem\??)?\s*", "", first, flags=re.I)
        items.append((f"Chamado TOPdesk ({product}): {first[:90]}", part))
    return items


def _ki_items(body: str) -> list[tuple[str, str]]:
    """A KI starts at the heading whose own text (before the next heading) carries "Número da KI"; it runs until
    the next KI. Works for "# T" + "- **Número da KI:**", "## T" + "**Número da KI:**" and the packaged "### T"."""
    heads = list(_HEADING.finditer(body))
    starts = []
    for j, h in enumerate(heads):
        own = body[h.end(): heads[j + 1].start() if j + 1 < len(heads) else len(body)]
        if "Número da KI" in own:
            starts.append(h)
    return [(h.group(2), body[h.start(): starts[k + 1].start() if k + 1 < len(starts) else len(body)])
            for k, h in enumerate(starts)]


def split_package(text: str) -> list[tuple[int, str, dict[str, str]]]:
    """[(section_no, text, {title, fonte, product, doc_type})] for each KI or ticket in a package or collection file."""
    # The exporter sometimes glues the next title to a separator or tag: "---# Título", "</ul>### Benefícios".
    text = re.sub(r"(---|</\w+>)(#{1,6} )", r"\1\n\2", text)
    marks = list(_FONTE.finditer(text))
    if marks:
        sources = [(m.group(1), text[m.end(): marks[i + 1].start() if i + 1 < len(marks) else len(text)])
                   for i, m in enumerate(marks)]
    else:  # a standalone "# Coleção de KIs — X" / "# Perguntas frequentes — X" file
        first = _HEADING.search(text)
        sources = [(first.group(2) if first else "Documento", text)]
    out: list[tuple[int, str, dict[str, str]]] = []
    for fonte, body in sources:
        body = _FIM.split(body)[0]
        meta = _source_meta(fonte)
        items = _ticket_items(body, meta["product"]) if meta["doc_type"] == "Chamado" else _ki_items(body)
        if not items and meta["doc_type"] != "Chamado":
            items = [(fonte, body)]  # a manual or other document: one section, chunked later
        whole = items == [(fonte, body)]
        for title, raw in items:
            content = clean_markup(raw)
            placeholder = title.startswith(("Sem título", "Coleção de KIs", "Perguntas frequentes")) and not whole
            if placeholder or len(content) < 80 or all(p in content for p in _PLACEHOLDER):
                continue
            ki = re.search(r"Número da KI:\**\s*(KI\s*\d+)", content)
            if ki and ki.group(1) not in title:
                title = f"{ki.group(1)} · {title}"
            out.append((len(out) + 1, content, {**meta, "title": title.strip()}))
    return out


def chunk_text(text: str, size: int = 1200, overlap: int = 200) -> list[str]:
    text = re.sub(r"[ \t]+", " ", text or "").strip()
    text = re.sub(r"\n{3,}", "\n\n", text)
    if not text:
        return []
    if len(text) <= size:
        return [text]
    chunks, start = [], 0
    while start < len(text):
        end = min(start + size, len(text))
        if end < len(text):
            # prefer breaking at a paragraph or sentence boundary
            cut = max(text.rfind("\n\n", start, end), text.rfind(". ", start, end))
            if cut > start + size // 2:
                end = cut + 1
        chunks.append(text[start:end].strip())
        if end >= len(text):
            break
        start = max(end - overlap, start + 1)
    return [c for c in chunks if c]


def infer_metadata(name: str, path: str = "") -> dict[str, str]:
    hay = f"{path}/{name}"
    product = next((p for p in KNOWN_PRODUCTS if p.lower() in hay.lower()), "")
    doc_type = next((t for pat, t in DOC_TYPES if re.search(pat, name, re.I)), "")
    if not doc_type:
        doc_type = next((t for pat, t in DOC_TYPES if re.search(pat, path, re.I)), "Documento")
    parts = [p for p in path.split("/") if p]
    module = ""
    if product and parts:
        # first folder under the product folder, when present
        lowered = [p.lower() for p in parts]
        for i, p in enumerate(lowered):
            if product.lower() in p and i + 1 < len(parts):
                module = parts[i + 1]
                break
    return {"product": product, "module": module, "doc_type": doc_type}
