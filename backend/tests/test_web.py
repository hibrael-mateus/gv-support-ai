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
    from app.llm import pick_gemini_model

    names = ["gemini-2.0-flash", "gemini-2.5-flash", "gemini-2.5-flash-lite", "gemini-3.0-flash-preview", "gemini-2.5-pro"]
    assert pick_gemini_model(names) == "gemini-2.5-flash"
    assert pick_gemini_model(["gemini-9-flash-preview", "gemini-9-flash-lite"]) == "gemini-9-flash-preview"
    assert pick_gemini_model([]) == "gemini-flash-latest"
