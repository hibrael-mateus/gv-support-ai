"""Text extraction, chunking and metadata inference for knowledge sources and attachments."""
from __future__ import annotations

import csv
import io
import re
import zipfile
from pathlib import PurePath

TEXT_EXT = {".txt", ".md", ".log", ".sql", ".ps1", ".psm1", ".xml", ".json", ".csv", ".ini", ".config",
            ".cs", ".js", ".ts", ".html", ".htm", ".bat", ".cmd", ".yaml", ".yml", ".rtm", ".tsv"}

KNOWN_PRODUCTS = ["GVcollege PRO", "GVcollege", "GVmobile", "GVcentris", "GVerp", "GVsign", "GVquest",
                  "Portal do Professor", "Portal Professor", "Portal do Aluno", "Pergamum", "EDUmessenger",
                  "Gestão de Contratos", "SaaS", "Serviços"]

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
    if ext == ".csv" or ext == ".tsv" or mime == "text/csv":
        text = decode_bytes(data)
        reader = csv.reader(io.StringIO(text), delimiter="\t" if ext == ".tsv" else ",")
        return [(0, "\n".join(" | ".join(r) for r in reader))]
    if ext in TEXT_EXT or mime.startswith("text/") or not ext:
        return [(0, decode_bytes(data))]
    raise ValueError(f"Formato não suportado para extração de texto: {ext or mime}")


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
