from __future__ import annotations

import difflib
import logging
import os
import threading
import time
from contextlib import asynccontextmanager
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from . import __version__, cases, drive, embedded, internet, jobs, maintenance, rag, web
from .agents import ACTIONS, GVSupportOrchestrator
from .agents.logs import analyze_log, summary_markdown
from .agents.powershell import ALL_MODULES, MODULES, build_diagnostic
from .agents.specialists import DocumentationAgent, SimilarCaseAgent
from .agents.sql import correction_script, discovery_script, guard_sql
from .db import get_meta, init_db
from .extract import extract_pages
from .llm import LLMUnavailable, get_provider
from .security import SecretMaskingFilter, classify_powershell, classify_sql
from .settings import (ALLOWED_GOOGLE_DRIVE_FOLDER_ID, APP_NAME, ATTACH_DIR, DATA_DIR, LOG_DIR, get_secret,
                       load_config, save_config, set_secret)

# ---- logging (secrets are masked before anything reaches disk) ----------------
_handler = RotatingFileHandler(LOG_DIR / "backend.log", maxBytes=2_000_000, backupCount=3, encoding="utf-8")
_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
_handler.addFilter(SecretMaskingFilter())
logging.basicConfig(level=logging.INFO, handlers=[_handler])
log = logging.getLogger("gvsupport")

API_TOKEN = os.getenv("GV_API_TOKEN", "")
SECRET_NAMES = {"openai_api_key", "gemini_api_key", "groq_api_key", "custom_api_key"}

@asynccontextmanager
async def lifespan(_: FastAPI):
    if web.ENABLED:
        web.restore_db()
    init_db()
    threading.Thread(target=_auto_sync_loop, daemon=True, name="auto-sync").start()
    if web.ENABLED:
        web.start_snapshots()
        cfg = load_config()
        if drive.status()["connected"] and not rag.stats()["chunks"]:
            _start_sync(False)  # fresh server: build the index right away
        if cfg.get("llm_provider") == "embedded" and cfg.get("embedded_model") in embedded.MODELS \
                and not embedded.is_gguf(embedded.model_path(cfg["embedded_model"])):
            jobs.start("model_download", lambda ctx: embedded.download(cfg["embedded_model"], ctx))
    log.info("backend started v%s data=%s web=%s", __version__, DATA_DIR, web.ENABLED)
    yield
    embedded.stop()
    if web.ENABLED and web.DATASET:
        try:
            web.snapshot_db()
        except Exception as exc:  # shutting down: never block on the network
            log.warning("final snapshot failed: %s", type(exc).__name__)


app = FastAPI(title=APP_NAME, version=__version__, lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173", "tauri://localhost", "http://tauri.localhost",
                   "https://tauri.localhost"],
    allow_methods=["*"], allow_headers=["*"],
)


@app.middleware("http")
async def require_token(request: Request, call_next):
    if web.ENABLED:
        return await web.guard(request, call_next)
    # The desktop shell generates a random token per launch; other local processes can't use the API.
    if API_TOKEN and request.method != "OPTIONS" and request.url.path != "/health":
        if request.headers.get("x-gv-token") != API_TOKEN:
            return JSONResponse({"detail": "Não autorizado"}, status_code=401)
    return await call_next(request)


@app.exception_handler(KeyError)
async def not_found(_: Request, exc: KeyError):
    return JSONResponse({"detail": f"Não encontrado: {exc}"}, status_code=404)


@app.exception_handler(PermissionError)
async def forbidden(_: Request, exc: PermissionError):
    return JSONResponse({"detail": str(exc)}, status_code=403)


@app.exception_handler(ValueError)
async def bad_request(_: Request, exc: ValueError):
    return JSONResponse({"detail": str(exc)}, status_code=400)


def _auto_sync_loop() -> None:
    while True:
        time.sleep(60)
        minutes = int(load_config().get("auto_sync_minutes") or 0)
        if not minutes or not drive.status()["connected"]:
            continue
        last = get_meta("last_sync", "")
        from datetime import datetime, timezone

        due = not last or (datetime.now(timezone.utc) - datetime.fromisoformat(last)).total_seconds() > minutes * 60
        if due:
            _start_sync(False)


# ---- models ----------------------------------------------------------------
class CaseIn(BaseModel):
    title: str = ""
    customer: str = ""
    product: str = ""
    module: str = ""
    routine: str = ""
    menu: str = ""
    screen: str = ""
    error_message: str = ""
    description: str = ""
    environment: str = ""
    server: str = ""
    database_name: str = ""
    already_validated: str = ""


class CasePatch(BaseModel):
    title: str | None = None
    status: str | None = None
    root_cause: str | None = None
    resolution: str | None = None
    description: str | None = None


class InvestigateIn(BaseModel):
    message: str = ""
    action: str = "investigar"


class FactIn(BaseModel):
    key: str
    value: str
    status: str = ""


class HypothesisIn(BaseModel):
    title: str
    rationale: str = ""
    test: str = ""
    status: str = "Não validada"
    evidence: str = ""


class HypothesisPatch(BaseModel):
    title: str | None = None
    rationale: str | None = None
    test: str | None = None
    status: str | None = None
    evidence: str | None = None


class ChatIn(BaseModel):
    message: str
    use_sources: bool = True


class SecretIn(BaseModel):
    name: str
    value: str = ""


class SqlIn(BaseModel):
    term: str = ""


class SqlCorrectionIn(BaseModel):
    table: str
    where: str
    set_clause: str = ""
    delete: bool = False


class PowerShellIn(BaseModel):
    modules: list[str] = Field(default_factory=lambda: ["sistema", "disco", "servicos", "rede", "eventos"])
    target: str = ""
    sql_instance: str = ""
    urls: list[str] = Field(default_factory=list)
    log_path: str = ""
    hours: int = 24


class ClassifyIn(BaseModel):
    language: str
    code: str


class TextIn(BaseModel):
    text: str


class CompareIn(BaseModel):
    a: str
    b: str
    name_a: str = "A"
    name_b: str = "B"


class FeedbackIn(BaseModel):
    useful: bool
    reason: str = ""
    comment: str = ""


class PathIn(BaseModel):
    path: str = ""


class ScriptIn(BaseModel):
    script: str


# ---- health / status / settings -----------------------------------------------
@app.get("/health")
def health():
    return {"app": APP_NAME, "version": __version__, "backend": "online"}


@app.get("/status")
def status():
    ai = get_provider().status()
    st = rag.stats()
    last_sync = get_meta("last_sync", "")
    drv = drive.status()
    sync_job = jobs.latest("sync")
    return {
        "version": __version__,
        "backend": "online",
        "ai": ai,
        "drive": drv,
        "rag": {"available": st["chunks"] > 0, **{k: st[k] for k in ("documents", "chunks", "vectorized_chunks", "errors")}},
        "index": {"last_sync": last_sync, "syncing": sync_job.get("state") == "running"},
        "internet": {"enabled": bool(load_config().get("internet_enabled"))},
        "allowed_folder_id": ALLOWED_GOOGLE_DRIVE_FOLDER_ID,
        "data_dir": str(DATA_DIR),
        "setup_completed": bool(load_config().get("setup_completed")),
    }


class LoginIn(BaseModel):
    password: str


@app.post("/auth/login")
def auth_login(body: LoginIn, request: Request):
    return web.login(request, body.password)


@app.post("/auth/admin")
def auth_admin(body: LoginIn, request: Request):
    return web.login(request, body.password, admin=True)


@app.get("/settings")
def get_settings(request: Request):
    cfg = load_config()
    cfg["web"] = web.ENABLED
    # the desktop app belongs to its user; on the site only the admin password opens Administração
    cfg["admin"] = not web.ENABLED or getattr(request.state, "role", "") == "admin"
    cfg["secrets"] = {n: bool(get_secret(n)) for n in SECRET_NAMES}
    cfg["allowed_folder_id"] = ALLOWED_GOOGLE_DRIVE_FOLDER_ID
    return cfg


@app.put("/settings")
def put_settings(changes: dict[str, Any]):
    return save_config(changes)


@app.put("/settings/secret")
def put_secret(body: SecretIn):
    if body.name not in SECRET_NAMES:
        raise HTTPException(400, "Segredo desconhecido")
    set_secret(body.name, body.value)
    return {"name": body.name, "configured": bool(body.value)}


@app.get("/ai/models")
def ai_models():
    p = get_provider()
    return {"provider": p.name, "models": p.list_models()}


@app.post("/ai/test")
def ai_test():
    p = get_provider()
    start = time.time()
    try:
        answer = p.chat([{"role": "user", "content": "Responda apenas: OK"}])
        emb = p.embed(["teste"])
        return {"ok": True, "answer": answer.strip()[:200], "seconds": round(time.time() - start, 1),
                "embeddings": bool(emb), "model": getattr(p, "resolved_model", lambda: p.model)()}
    except LLMUnavailable as exc:
        return {"ok": False, "error": str(exc)}


@app.get("/ai/embedded")
def ai_embedded():
    cfg = load_config()
    return {"binary": bool(embedded.server_binary()), "selected": cfg.get("embedded_model"),
            "custom_path": cfg.get("embedded_model_path", ""),
            "models": [{"key": k, "label": m["label"], "downloaded": embedded.is_gguf(embedded.model_path(k))}
                       for k, m in embedded.MODELS.items()]}


@app.post("/ai/embedded/download")
def ai_embedded_download(body: TextIn):
    if body.text not in embedded.MODELS:
        raise HTTPException(400, "Modelo desconhecido")
    save_config({"llm_provider": "embedded", "embedded_model": body.text, "embedded_model_path": ""})
    return jobs.start("model_download", lambda ctx: embedded.download(body.text, ctx))


@app.post("/ai/embedded/import")
def ai_embedded_import(body: PathIn):
    if not body.path.lower().endswith(".gguf") or not embedded.is_gguf(Path(body.path)):
        raise HTTPException(400, "Selecione um arquivo de modelo .gguf válido.")
    return save_config({"llm_provider": "embedded", "embedded_model_path": body.path})


# ---- Google Drive / sources ---------------------------------------------------
@app.get("/drive/status")
def drive_status():
    return drive.status()


@app.post("/drive/connect")
def drive_connect(body: PathIn):
    path = body.path or load_config().get("google_client_secret_path", "")
    if not path or not Path(path).exists():
        raise HTTPException(400, "Selecione o arquivo JSON do cliente OAuth (tipo 'App para computador').")
    save_config({"google_client_secret_path": path})
    return jobs.start("drive_auth", lambda ctx: drive.authorize(path))


@app.post("/drive/disconnect")
def drive_disconnect():
    drive.disconnect()
    return drive.status()


@app.get("/drive/folder")
def drive_folder():
    return drive.GoogleDriveGateway().folder_info()


def _start_sync(full: bool):
    embedder = get_provider().embed
    return jobs.start("sync", lambda ctx: drive.sync(ctx, full=full, embedder=embedder))


@app.post("/sources/sync")
def sources_sync(full: bool = False):
    if not drive.status()["connected"]:
        raise HTTPException(400, "Conecte o Google Drive antes de sincronizar.")
    return _start_sync(full)


UPLOAD_TYPES = {".md", ".txt", ".pdf", ".docx"}


@app.post("/sources/upload")
def sources_upload(files: list[UploadFile] = File(...)):
    """Administração: add MD/PDF/TXT/DOCX files to the knowledge base, next to the Drive folder."""
    done = []
    for f in files:
        name = Path(f.filename or "arquivo").name
        if Path(name).suffix.lower() not in UPLOAD_TYPES:
            raise HTTPException(400, f"{name}: envie arquivos .md, .pdf, .txt ou .docx.")
        data = f.file.read()
        if len(data) > 50 * 1024 * 1024:
            raise HTTPException(413, f"{name}: arquivo maior que 50 MB.")
        pages = extract_pages(name, data, f.content_type or "")
        if not any(t.strip() for _, t, *_ in pages):
            raise HTTPException(400, f"{name}: não há texto para indexar (PDF digitalizado como imagem?).")
        chunks = rag.index_upload(name, data, pages, chunk_size=int(load_config().get("chunk_size", 1200)))
        done.append({"name": name, "chunks": chunks})
    return {"indexed": done}


@app.delete("/sources/{drive_file_id}")
def sources_delete(drive_file_id: str):
    if not drive_file_id.startswith(rag.UPLOAD_PREFIX):
        raise HTTPException(400, "Fontes do Google Drive saem do índice quando são removidas da pasta autorizada.")
    rag.remove_document(drive_file_id)
    return {"deleted": drive_file_id}


@app.get("/jobs/{job_id}")
def job(job_id: str):
    data = jobs.get(job_id)
    if not data:
        raise HTTPException(404, "Tarefa não encontrada")
    return data


@app.get("/jobs/latest/{kind}")
def job_latest(kind: str):
    return jobs.latest(kind)


@app.get("/sources/stats")
def sources_stats():
    return {**rag.stats(), "last_sync": get_meta("last_sync", "")}


@app.get("/sources")
def sources_list(q: str = "", doc_type: str = "", product: str = "", limit: int = 300):
    from .db import connection

    sql = "SELECT drive_file_id,name,path,doc_type,product,module,modified_time,chunks,web_url,uses,indexed_at FROM sources WHERE 1=1"
    args: list[Any] = []
    if q:
        sql += " AND (name LIKE ? OR path LIKE ?)"
        args += [f"%{q}%", f"%{q}%"]
    if doc_type:
        sql += " AND doc_type=?"
        args.append(doc_type)
    if product:
        sql += " AND product=?"
        args.append(product)
    sql += " ORDER BY name LIMIT ?"
    args.append(limit)
    with connection() as conn:
        return [dict(r) for r in conn.execute(sql, args)]


@app.get("/sources/errors")
def sources_errors():
    from .db import connection

    with connection() as conn:
        return [dict(r) for r in conn.execute("SELECT * FROM index_errors ORDER BY id DESC LIMIT 500")]


@app.get("/sources/search")
def sources_search(q: str, limit: int = 10, product: str = "", doc_type: str = "", module: str = ""):
    p = get_provider()
    hits = rag.search(q, limit, product=product, doc_type=doc_type, module=module, embedder=p.embed)
    return [h.as_dict() for h in hits]


@app.get("/sources/{drive_file_id}/chunks")
def source_chunks(drive_file_id: str):
    from .db import connection

    with connection() as conn:
        src = conn.execute("SELECT * FROM sources WHERE drive_file_id=?", (drive_file_id,)).fetchone()
        if not src:
            raise HTTPException(404, "Fonte não encontrada")
        chunks = [dict(r) for r in conn.execute(
            "SELECT id,page,ordinal,content FROM chunks WHERE drive_file_id=? ORDER BY page, ordinal", (drive_file_id,))]
    return {"source": dict(src), "chunks": chunks}


# ---- dashboard / cases -----------------------------------------------------------
@app.get("/dashboard")
def dashboard():
    data = cases.dashboard()
    st = rag.stats()
    data.update(sources=st["documents"], last_sync=get_meta("last_sync", ""), most_used=st["most_used"],
                ai=get_provider().status())
    return data


@app.get("/cases")
def list_cases(status: str = "", q: str = ""):
    return cases.list_cases(status, q)


@app.post("/cases")
def create_case(body: CaseIn):
    return cases.create_case(body.model_dump())


@app.get("/cases/{case_id}")
def get_case(case_id: int):
    return cases.get_case(case_id)


@app.patch("/cases/{case_id}")
def patch_case(case_id: int, body: CasePatch):
    return cases.update_case(case_id, body.model_dump(exclude_none=True))


@app.delete("/cases/{case_id}")
def delete_case(case_id: int):
    cases.delete_case(case_id)
    return {"deleted": True}


@app.post("/cases/{case_id}/investigate")
def investigate(case_id: int, body: InvestigateIn):
    if body.action not in ACTIONS:
        raise HTTPException(400, "Ação desconhecida")
    return GVSupportOrchestrator().investigate(case_id, body.message, body.action)


@app.get("/cases/{case_id}/messages")
def case_messages(case_id: int):
    return cases.list_messages(case_id)


@app.post("/cases/{case_id}/facts")
def add_fact(case_id: int, body: FactIn):
    return cases.upsert_fact(case_id, body.key, body.value, body.status)


@app.delete("/facts/{fact_id}")
def delete_fact(fact_id: int):
    cases.delete_fact(fact_id)
    return {"deleted": True}


@app.post("/cases/{case_id}/hypotheses")
def add_hypothesis(case_id: int, body: HypothesisIn):
    return cases.add_hypothesis(case_id, body.title, body.rationale, body.test, body.status, body.evidence)


@app.patch("/hypotheses/{hyp_id}")
def patch_hypothesis(hyp_id: int, body: HypothesisPatch):
    return cases.update_hypothesis(hyp_id, body.model_dump(exclude_none=True))


def _save_upload(case_id: int | None, upload: UploadFile) -> tuple[dict[str, Any], str]:
    data = upload.file.read()
    if len(data) > 50 * 1024 * 1024:
        raise HTTPException(413, "Arquivo maior que 50 MB")
    folder = ATTACH_DIR / (str(case_id) if case_id else "chat")
    folder.mkdir(parents=True, exist_ok=True)
    name = Path(upload.filename or "arquivo").name
    dest = folder / f"{int(time.time())}-{name}"
    dest.write_bytes(data)
    try:
        text = "\n".join(t for _, t in extract_pages(name, data, upload.content_type or ""))
    except Exception:
        text = ""  # images and unsupported formats are stored as evidence without text
    att = cases.add_attachment(case_id, name, str(dest), len(data), text)
    return att, text


@app.post("/cases/{case_id}/attachments")
def upload_attachment(case_id: int, file: UploadFile = File(...)):
    cases.get_case(case_id)
    att, text = _save_upload(case_id, file)
    return {**att, "has_text": bool(text.strip())}


# ---- chat ---------------------------------------------------------------------
@app.get("/chat/messages")
def chat_messages():
    return cases.list_messages(None)


@app.post("/chat")
def chat(body: ChatIn):
    return GVSupportOrchestrator().chat(body.message, body.use_sources)


@app.post("/chat/upload")
def chat_upload(file: UploadFile = File(...), message: str = Form("")):
    _, text = _save_upload(None, file)
    prompt = f"{message}\n\n[Arquivo: {file.filename}]\n{text[:30000]}" if text else f"{message}\n\n[Arquivo sem texto extraível: {file.filename}]"
    return GVSupportOrchestrator().chat(prompt.strip(), True)


@app.delete("/chat/messages")
def chat_clear():
    cases.clear_free_chat()
    return {"cleared": True}


@app.post("/messages/{message_id}/feedback")
def feedback(message_id: int, body: FeedbackIn):
    return cases.add_feedback(message_id, body.useful, body.reason, body.comment)


# ---- tools ----------------------------------------------------------------------
@app.post("/tools/sql")
def tool_sql(body: SqlIn):
    return discovery_script(body.term).as_dict()


@app.post("/tools/sql/correction")
def tool_sql_correction(body: SqlCorrectionIn):
    return correction_script(body.table, body.where, body.set_clause, body.delete).as_dict()


@app.post("/tools/sql/check")
def tool_sql_check(body: TextIn):
    return [s.as_dict() for s in guard_sql(body.text, "", "SQL verificado")]


@app.get("/tools/powershell/modules")
def tool_ps_modules():
    return [{"id": k, "label": v[0]} for k, v in MODULES.items()]


@app.post("/tools/powershell")
def tool_powershell(body: PowerShellIn):
    mods = [m for m in body.modules if m in ALL_MODULES]
    return build_diagnostic(mods, target=body.target, sql_instance=body.sql_instance, urls=body.urls,
                            log_path=body.log_path, hours=body.hours).as_dict()


@app.post("/tools/classify")
def tool_classify(body: ClassifyIn):
    rep = classify_sql(body.code) if body.language.lower() in ("sql", "tsql") else classify_powershell(body.code)
    return rep.as_dict()


@app.post("/tools/log")
def tool_log(file: UploadFile | None = File(None), text: str = Form("")):
    content = text
    if file is not None:
        data = file.file.read()
        try:
            content = "\n".join(t for _, t in extract_pages(file.filename or "log.txt", data, file.content_type or ""))
        except ValueError:
            content = data.decode("utf-8", errors="replace")
    if not content.strip():
        raise HTTPException(400, "Envie um arquivo de log ou cole o conteúdo.")
    result = analyze_log(content)
    return {"result": result, "markdown": summary_markdown(result)}


@app.post("/tools/similar")
def tool_similar(body: TextIn):
    p = get_provider()
    return SimilarCaseAgent(DocumentationAgent(p)).run(body.text).as_dict()


@app.post("/tools/compare")
def tool_compare(body: CompareIn):
    a, b = body.a.splitlines(), body.b.splitlines()
    diff = list(difflib.unified_diff(a, b, body.name_a, body.name_b, lineterm="", n=2))
    ratio = difflib.SequenceMatcher(None, body.a, body.b).ratio()
    return {"similarity": round(ratio * 100, 1), "diff": "\n".join(diff),
            "added": sum(1 for l in diff if l.startswith("+") and not l.startswith("+++")),
            "removed": sum(1 for l in diff if l.startswith("-") and not l.startswith("---"))}


@app.post("/tools/execute")
def tool_execute(body: ScriptIn):
    return maintenance.run_powershell(body.script)


@app.get("/internet/search")
def internet_search(q: str):
    if not load_config().get("internet_enabled"):
        raise HTTPException(403, "Internet auxiliar desabilitada nas configurações.")
    if not internet.is_allowed_query(q):
        raise HTTPException(400, "Informações internas GV Dasa não são pesquisadas na internet; use as fontes autorizadas.")
    return internet.search_microsoft_learn(q)


# ---- backup / updates ------------------------------------------------------------
@app.post("/backup/export")
def backup_export():
    return {"path": str(maintenance.export_backup())}


@app.post("/backup/import")
def backup_import(body: PathIn):
    if not body.path or not Path(body.path).is_file():
        raise HTTPException(400, "Selecione o arquivo de backup (.zip).")
    return maintenance.import_backup(Path(body.path))


@app.get("/updates/check")
def updates_check():
    return maintenance.check_updates()


@app.get("/logs/path")
def logs_path():
    return {"path": str(LOG_DIR)}


# Website mode: the built UI is served by this same app (registered last so API routes win).
if web.WEB_DIR:
    from fastapi.staticfiles import StaticFiles

    app.mount("/", StaticFiles(directory=web.WEB_DIR, html=True), name="ui")
