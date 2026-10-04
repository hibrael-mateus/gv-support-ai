from fastapi.testclient import TestClient

from app import web
from app.main import app


def _client(monkeypatch, tmp_path):
    (tmp_path / "index.html").write_text("<html>GV</html>")
    monkeypatch.setattr(web, "ENABLED", True)
    monkeypatch.setattr(web, "WEB_DIR", tmp_path)
    monkeypatch.setenv("GV_WEB_PASSWORD", "senha-do-time")
    monkeypatch.setattr(web.time, "sleep", lambda s: None)
    web._fails.clear()
    return TestClient(app)


def test_web_requires_login_and_blocks_server_side_actions(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    assert c.get("/cases").status_code == 401
    assert c.post("/auth/login", json={"password": "errada"}).status_code == 403
    token = c.post("/auth/login", json={"password": "senha-do-time"}).json()["token"]
    h = {"x-gv-token": token}
    assert c.get("/cases", headers=h).status_code == 200
    assert c.get("/settings", headers=h).json()["web"] is True
    for method, path in (("post", "/tools/execute"), ("put", "/settings"), ("put", "/settings/secret"),
                         ("post", "/backup/import"), ("post", "/drive/connect"), ("post", "/ai/embedded/import")):
        assert getattr(c, method)(path, headers=h, json={}).status_code == 403, path
    assert c.get("/cases", headers={"x-gv-token": token[:-1] + ("1" if token[-1] == "0" else "0")}).status_code == 401


def test_login_is_rate_limited(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    for _ in range(10):
        c.post("/auth/login", json={"password": "x"})
    r = c.post("/auth/login", json={"password": "senha-do-time"})
    assert r.status_code == 403 and "tentativas" in r.json()["detail"]


def test_static_ui_is_public_but_cannot_escape_its_folder(monkeypatch, tmp_path):
    (tmp_path / "ui").mkdir()
    _client(monkeypatch, tmp_path / "ui")
    assert web._static_file("/") and web._static_file("/index.html")
    assert not web._static_file("/../index.html") and not web._static_file("/%2e%2e/x")


def test_server_secrets_and_config_from_environment(monkeypatch):
    from app.settings import get_secret, load_config

    monkeypatch.setenv("GV_SECRET_GROQ_API_KEY", "k")
    monkeypatch.setenv("GV_CONFIG_LLM_PROVIDER", "groq")
    monkeypatch.setenv("GV_CONFIG_AUTO_SYNC_MINUTES", "240")
    assert get_secret("groq_api_key") == "k"
    cfg = load_config()
    assert cfg["llm_provider"] == "groq" and cfg["auto_sync_minutes"] == 240


def test_gemini_defaults_to_newest_stable_flash():
    from app.llm import gemini_candidates, pick_gemini_model

    names = ["gemini-2.0-flash", "gemini-2.5-flash", "gemini-2.5-flash-lite", "gemini-3.0-flash-preview", "gemini-2.5-pro"]
    assert pick_gemini_model(names) == "gemini-2.5-flash"
    assert gemini_candidates(names) == ["gemini-2.5-flash", "gemini-2.0-flash", "gemini-3.0-flash-preview",
                                        "gemini-flash-latest"]
    assert pick_gemini_model([]) == "gemini-flash-latest"


def test_gemini_falls_back_when_overloaded_and_never_leaks_the_key(monkeypatch):
    import httpx

    from app.llm import GeminiProvider, LLMUnavailable

    key = "AQ.Ab8RN6Jc2HLF9eHCHhvjDS6eUrW-Ic3RT4F"
    calls = []

    def post(url, headers=None, **_):
        calls.append(url)
        assert key not in url and headers["x-goog-api-key"] == key
        if "2.5" in url:
            return httpx.Response(503, request=httpx.Request("POST", url))
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": "ok"}]}}]})

    p = GeminiProvider(key)
    monkeypatch.setattr(p, "list_models", lambda: ["gemini-2.5-flash", "gemini-2.0-flash"])
    monkeypatch.setattr(httpx, "post", post)
    assert p.chat([{"role": "user", "content": "oi"}]) == "ok" and len(calls) == 2

    monkeypatch.setattr(httpx, "post", lambda url, **_: httpx.Response(503, request=httpx.Request("POST", url)))
    p.model = ""
    try:
        p.chat([{"role": "user", "content": "oi"}])
        raise AssertionError("expected LLMUnavailable")
    except LLMUnavailable as exc:
        assert "503" in str(exc) and key not in str(exc)
    assert key not in str(LLMUnavailable(f"error for url 'https://x/y?key={key}&a=1'"))


def test_admin_role_unlocks_administracao_only(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    team = {"x-gv-token": c.post("/auth/login", json={"password": "senha-do-time"}).json()["token"]}
    assert c.get("/settings", headers=team).json()["admin"] is False
    assert c.put("/settings", headers=team, json={}).status_code == 403
    assert c.post("/sources/upload", headers=team, files={"files": ("a.md", b"x")}).status_code == 403
    assert c.post("/auth/admin", json={"password": "senha-do-time"}).status_code == 403  # admin password not set
    monkeypatch.setenv("GV_ADMIN_PASSWORD", "senha-admin")
    admin = {"x-gv-token": c.post("/auth/admin", json={"password": "senha-admin"}).json()["token"]}
    assert c.get("/settings", headers=admin).json()["admin"] is True
    assert c.put("/settings", headers=admin, json={"top_k": 8}).status_code == 200
    assert c.post("/tools/execute", headers=admin, json={}).status_code == 403  # never on the server
    forged = team["x-gv-token"].replace(".team.", ".admin.")
    assert c.get("/cases", headers={"x-gv-token": forged}).status_code == 401


def test_uploaded_sources_are_searchable_survive_reindex_and_can_be_deleted():
    from app import rag

    client = TestClient(app)
    md = "# Emissão de boletim no Portal 2.0\nPara emitir o boletim no Portal do Aluno 2.0, acesse Documentos > Boletim e clique em Gerar PDF.".encode()
    r = client.post("/sources/upload", files=[("files", ("boletim-portal.md", md, "text/markdown"))])
    assert r.status_code == 200 and r.json()["indexed"][0]["chunks"] >= 1
    assert client.post("/sources/upload", files={"files": ("x.exe", b"MZ")}).status_code == 400
    hits = rag.search("como emitir o boletim no portal 2.0", 3)
    assert hits and hits[0].source_name == "boletim-portal.md"
    rag.clear_index()  # Drive reindex
    fid = [s["drive_file_id"] for s in client.get("/sources").json() if s["name"] == "boletim-portal.md"][0]
    assert fid.startswith("upload:")
    assert client.delete(f"/sources/{fid}").status_code == 200
    assert client.delete("/sources/drive-file-id").status_code == 400
    assert not rag.search("como emitir o boletim no portal 2.0", 3)
