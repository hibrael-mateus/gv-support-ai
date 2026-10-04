"""Hybrid RAG: SQLite FTS5 (BM25) + dense vectors + metadata boosts, fused with RRF, then reranked.

Vector store: embeddings are float32 BLOBs in the same SQLite file, searched with numpy.
ponytail: brute-force cosine is exact and ~ms for tens of thousands of chunks on a desktop;
swap for an ANN index (hnswlib/Qdrant local) if the authorized folder grows past ~200k chunks.
"""
from __future__ import annotations

import hashlib
import math
import re
import threading
import unicodedata
from collections.abc import Callable
from dataclasses import asdict, dataclass

import numpy as np

from .db import connection
from .extract import KNOWN_PRODUCTS, chunk_text, infer_metadata
from .security import enforce_allowed_source, mask_secrets
from .settings import ALLOWED_GOOGLE_DRIVE_FOLDER_ID

STOPWORDS = set("""a o e é de da do das dos em no na nos nas um uma uns umas para por com sem que se ao aos à às ou
como mais menos ser está esta este isso isto qual quais quando onde porque pois não sim the and of to in on for
erro ao""".split())


# Words every support request uses; they help ranking but must not decide whether a source answers it.
GENERIC = set("""como configurar configuracao cadastrar cadastro fazer realizar possivel sistema cliente clientes informa
relata relatam problema problemas consegue conseguem conseguindo conseguir aparece aparecem funciona funcionar usuario
usuarios favor verificar ajuda ajustar ajuste tela opcao novo nova quando onde porque esta estao tentar tentando""".split())


@dataclass
class SearchHit:
    chunk_id: int
    drive_file_id: str
    source_name: str
    doc_type: str
    product: str
    module: str
    page: int
    content: str
    excerpt: str
    relevance: float  # 0..100
    modified_time: str
    web_url: str
    path: str

    def as_dict(self) -> dict:
        return asdict(self)


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in text if not unicodedata.combining(c))


def query_terms(query: str) -> list[str]:
    terms = re.findall(r"[\w.]+", normalize(query))
    return [t for t in dict.fromkeys(terms) if len(t) > 1 and t not in STOPWORDS]


# ---- vector cache -----------------------------------------------------------
class _VectorCache:
    def __init__(self):
        self.lock = threading.Lock()
        self.version = -1
        self.ids: np.ndarray = np.zeros(0, dtype=np.int64)
        self.matrix: np.ndarray = np.zeros((0, 0), dtype=np.float32)

    def get(self) -> tuple[np.ndarray, np.ndarray]:
        with self.lock:
            current = _index_version()
            if current != self.version:
                with connection() as conn:
                    rows = conn.execute("SELECT id, embedding FROM chunks WHERE embedding IS NOT NULL").fetchall()
                if rows:
                    vecs = [np.frombuffer(r["embedding"], dtype=np.float32) for r in rows]
                    dim = max(len(v) for v in vecs)
                    keep = [(r["id"], v) for r, v in zip(rows, vecs) if len(v) == dim]
                    self.ids = np.array([k[0] for k in keep], dtype=np.int64)
                    m = np.vstack([k[1] for k in keep])
                    self.matrix = m / np.maximum(np.linalg.norm(m, axis=1, keepdims=True), 1e-9)
                else:
                    self.ids, self.matrix = np.zeros(0, dtype=np.int64), np.zeros((0, 0), dtype=np.float32)
                self.version = current
            return self.ids, self.matrix


_vectors = _VectorCache()
_version_lock = threading.Lock()
_version = 0


def _index_version() -> int:
    return _version


def _bump_version() -> None:
    global _version
    with _version_lock:
        _version += 1


# ---- indexing ---------------------------------------------------------------
def content_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def index_document(
    *,
    drive_file_id: str,
    name: str,
    pages: list[tuple[int, str]],
    parents_lookup: Callable[[str], list[str]],
    mime_type: str = "",
    path: str = "",
    folder_id: str = "",
    modified_time: str = "",
    file_hash: str = "",
    web_url: str = "",
    embedder: Callable[[list[str]], list[list[float]] | None] | None = None,
    chunk_size: int = 1200,
    allowed_folder_id: str = ALLOWED_GOOGLE_DRIVE_FOLDER_ID,
) -> int:
    """Index one Drive file. The ancestry check happens HERE so no caller can bypass it."""
    enforce_allowed_source(drive_file_id, parents_lookup, allowed_folder_id)
    meta = infer_metadata(name, path)
    # rows: (page, ordinal, chunk, section title, product, doc_type). Package files carry per-section metadata.
    rows: list[tuple[int, int, str, str, str, str]] = []
    for page, text, *extra in pages:
        sec = extra[0] if extra else {}
        title = sec.get("title", "")
        # Sources exported from TOPdesk/SharePoint can carry real passwords; never index or display them.
        for i, chunk in enumerate(chunk_text(mask_secrets(text), chunk_size)):
            # the section title travels with every chunk so BM25, embeddings and the excerpt all see it
            body = chunk if not title or chunk.startswith(title) else f"{title}\n{chunk}"
            rows.append((page, i, body, title, sec.get("product") or meta["product"], sec.get("doc_type") or meta["doc_type"]))
    vectors = None
    if embedder and rows:
        vectors = []
        for start in range(0, len(rows), 32):
            batch = embedder([f"{name}\n{r[2]}" for r in rows[start:start + 32]])
            if not batch:
                vectors = None
                break
            vectors.extend(batch)
    with connection() as conn:
        _delete_chunks(conn, drive_file_id)
        conn.execute(
            """INSERT INTO sources(drive_file_id,name,mime_type,path,folder_id,authorized_root,product,module,doc_type,
                                   modified_time,hash,chunks,web_url,indexed_at)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,CURRENT_TIMESTAMP)
               ON CONFLICT(drive_file_id) DO UPDATE SET name=excluded.name, mime_type=excluded.mime_type,
                 path=excluded.path, folder_id=excluded.folder_id, authorized_root=excluded.authorized_root,
                 product=excluded.product, module=excluded.module, doc_type=excluded.doc_type,
                 modified_time=excluded.modified_time, hash=excluded.hash, chunks=excluded.chunks,
                 web_url=excluded.web_url, indexed_at=CURRENT_TIMESTAMP""",
            (drive_file_id, name, mime_type, path, folder_id, allowed_folder_id, meta["product"], meta["module"],
             meta["doc_type"], modified_time, file_hash, len(rows), web_url),
        )
        for idx, (page, ordinal, chunk, section, product, doc_type) in enumerate(rows):
            blob = np.asarray(vectors[idx], dtype=np.float32).tobytes() if vectors else None
            cur = conn.execute(
                "INSERT INTO chunks(drive_file_id,page,ordinal,content,embedding,section,product,doc_type) VALUES(?,?,?,?,?,?,?,?)",
                (drive_file_id, page, ordinal, chunk, blob, section, product, doc_type),
            )
            conn.execute(
                "INSERT INTO chunks_fts(rowid,content,source_name,product,module,doc_type) VALUES(?,?,?,?,?,?)",
                (cur.lastrowid, chunk, section or name, product, meta["module"], doc_type),
            )
        conn.execute("DELETE FROM index_errors WHERE drive_file_id=?", (drive_file_id,))
    _bump_version()
    return len(rows)


def _delete_chunks(conn, drive_file_id: str) -> None:
    ids = [r[0] for r in conn.execute("SELECT id FROM chunks WHERE drive_file_id=?", (drive_file_id,))]
    conn.executemany("DELETE FROM chunks_fts WHERE rowid=?", [(i,) for i in ids])
    conn.execute("DELETE FROM chunks WHERE drive_file_id=?", (drive_file_id,))


def remove_document(drive_file_id: str) -> None:
    with connection() as conn:
        _delete_chunks(conn, drive_file_id)
        conn.execute("DELETE FROM sources WHERE drive_file_id=?", (drive_file_id,))
    _bump_version()


def clear_index() -> None:
    with connection() as conn:
        conn.execute("DELETE FROM chunks_fts")
        conn.execute("DELETE FROM chunks")
        conn.execute("DELETE FROM sources")
        conn.execute("DELETE FROM index_errors")
    _bump_version()


def record_error(drive_file_id: str, name: str, error: str) -> None:
    with connection() as conn:
        conn.execute("INSERT INTO index_errors(drive_file_id,name,error) VALUES(?,?,?)", (drive_file_id, name, error[:500]))


# ---- search -----------------------------------------------------------------
def stem(term: str) -> str:
    """Crude Portuguese stem: a prefix, so configurar/configure and integração/integrar meet."""
    return term if len(term) <= 5 else term[:max(5, math.ceil(len(term) * 0.75))]


def _fts_query(terms: list[str]) -> str:
    return " OR ".join(f'"{stem(t)}"*' if len(t) > 3 else f'"{t}"' for t in terms)


def _term_weights(terms: list[str]) -> dict[str, float]:
    """Smoothed IDF per query term from the FTS index; unseen terms get the maximum weight."""
    with connection() as conn:
        total = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0] or 1
        weights = {}
        for t in terms:
            df = conn.execute("SELECT COUNT(*) FROM chunks_fts WHERE chunks_fts MATCH ?", (_fts_query([t]),)).fetchone()[0]
            weights[t] = 0.1 if t in GENERIC else math.log((total + 1) / (df + 0.5))
    return {t: max(w, 0.05) for t, w in weights.items()}


def best_excerpt(content: str, terms: list[str], width: int = 420) -> str:
    """The exact passage of the chunk that best matches the query (shown as evidence)."""
    sentences = re.split(r"(?<=[.!?;:])\s+|\n+", content)
    best, best_score = "", -1
    for i in range(len(sentences)):
        window = " ".join(sentences[i:i + 3]).strip()
        if not window:
            continue
        norm = normalize(window)
        score = sum(1 for t in terms if stem(t) in norm)
        if score > best_score:
            best, best_score = window, score
    best = best or content
    return best if len(best) <= width else best[:width].rsplit(" ", 1)[0] + "…"


def search(
    query: str,
    limit: int = 8,
    *,
    product: str = "",
    doc_type: str = "",
    module: str = "",
    embedder: Callable[[list[str]], list[list[float]] | None] | None = None,
    allowed_folder_id: str = ALLOWED_GOOGLE_DRIVE_FOLDER_ID,
) -> list[SearchHit]:
    terms = query_terms(query)
    if not terms:
        return []
    pool = max(limit * 6, 40)
    ranks: dict[int, float] = {}

    with connection() as conn:
        lexical = conn.execute(
            "SELECT rowid AS id, bm25(chunks_fts, 1.0, 2.0, 1.0, 1.0, 1.0) AS score FROM chunks_fts "
            "WHERE chunks_fts MATCH ? ORDER BY score LIMIT ?",
            (_fts_query(terms), pool),
        ).fetchall()
    for rank, row in enumerate(lexical):
        ranks[row["id"]] = ranks.get(row["id"], 0) + 1 / (60 + rank)

    cosine: dict[int, float] = {}
    if embedder:
        qv = embedder([query])
        ids, matrix = _vectors.get()
        if qv and len(ids) and matrix.shape[1] == len(qv[0]):
            q = np.asarray(qv[0], dtype=np.float32)
            q /= max(float(np.linalg.norm(q)), 1e-9)
            sims = matrix @ q
            top = np.argsort(-sims)[:pool]
            for rank, i in enumerate(top):
                cid = int(ids[i])
                cosine[cid] = float(sims[i])
                ranks[cid] = ranks.get(cid, 0) + 1 / (60 + rank)

    if not ranks:
        return []
    weights = _term_weights(terms)
    mentioned_products = [p for p in KNOWN_PRODUCTS if normalize(p) in normalize(query)]
    placeholders = ",".join("?" * len(ranks))
    with connection() as conn:
        rows = conn.execute(
            f"""SELECT c.id, c.drive_file_id, c.page, c.content, c.section, s.name,
                       COALESCE(NULLIF(c.product,''), s.product) AS product, s.module,
                       COALESCE(NULLIF(c.doc_type,''), s.doc_type) AS doc_type,
                       s.modified_time, s.web_url, s.path, s.authorized_root
                FROM chunks c JOIN sources s ON s.drive_file_id=c.drive_file_id
                WHERE c.id IN ({placeholders})""",
            list(ranks),
        ).fetchall()

    hits: list[tuple[float, tuple[SearchHit, object]]] = []
    for r in rows:
        if r["authorized_root"] != allowed_folder_id:  # defense in depth
            continue
        if product and normalize(product) not in normalize(r["product"] or ""):
            continue
        if doc_type and normalize(doc_type) != normalize(r["doc_type"] or ""):
            continue
        if module and normalize(module) not in normalize(r["module"] or ""):
            continue
        norm = normalize(f"{r['name']} {r['content']}")
        # IDF-weighted: matching "gvcollege" or "erro" (everywhere) proves little; matching the rare terms does.
        coverage = sum(weights[t] for t in terms if stem(t) in norm) / sum(weights.values())
        phrase = 0.15 if len(terms) > 1 and " ".join(terms[:2]) in norm else 0.0
        meta = 0.1 if mentioned_products and any(normalize(p) in normalize(r["product"] or r["name"]) for p in mentioned_products) else 0.0
        cos = max(cosine.get(r["id"], 0.0), 0.0)
        relevance = (0.55 * coverage + 0.45 * cos) if cosine else coverage
        relevance = min(1.0, relevance + phrase + meta)
        final = ranks[r["id"]] * 30 + relevance  # RRF fused order, reranked by evidence quality
        hits.append((final, (SearchHit(
            chunk_id=r["id"], drive_file_id=r["drive_file_id"], source_name=r["section"] or r["name"],
            doc_type=r["doc_type"] or "", product=r["product"] or "", module=r["module"] or "",
            page=0 if r["section"] else r["page"] or 0, content=r["content"],
            excerpt=best_excerpt(r["content"], terms), relevance=round(relevance * 100, 1),
            modified_time=r["modified_time"] or "", web_url=r["web_url"] or "",
            path=f"{r['path'] or ''}/{r['name']}" if r["section"] else r["path"] or "",
        # the same KI/ticket is exported into several package files: cite it once
        ), normalize(r["section"]) if r["section"] else (r["drive_file_id"], r["page"]))))
    hits.sort(key=lambda x: -x[0])
    # one best chunk per section (or file page) keeps citations diverse
    seen, out = set(), []
    for _, (hit, key) in hits:
        if key in seen:
            continue
        seen.add(key)
        out.append(hit)
        if len(out) >= limit:
            break
    if out:
        with connection() as conn:
            conn.executemany("UPDATE sources SET uses=uses+1 WHERE drive_file_id=?", [(h.drive_file_id,) for h in out])
    return out


def stats() -> dict:
    with connection() as conn:
        total = conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0]
        chunks = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
        vectors = conn.execute("SELECT COUNT(*) FROM chunks WHERE embedding IS NOT NULL").fetchone()[0]
        # Package files hold many KIs/tickets: count the citable sections, not the files.
        by_type = {r[0] or "Documento": r[1] for r in conn.execute(
            "SELECT COALESCE(NULLIF(c.doc_type,''), s.doc_type) AS t, COUNT(DISTINCT c.drive_file_id || '|' || "
            "COALESCE(c.section,'')) FROM chunks c JOIN sources s ON s.drive_file_id=c.drive_file_id GROUP BY t")}
        by_product = {r[0] or "Sem produto": r[1] for r in conn.execute("SELECT product, COUNT(*) FROM sources GROUP BY product")}
        errors = conn.execute("SELECT COUNT(*) FROM index_errors").fetchone()[0]
        top = [dict(r) for r in conn.execute(
            "SELECT drive_file_id, name, doc_type, product, uses FROM sources WHERE uses>0 ORDER BY uses DESC LIMIT 8")]
    return {"documents": total, "chunks": chunks, "vectorized_chunks": vectors, "by_type": by_type,
            "by_product": by_product, "errors": errors, "most_used": top}
