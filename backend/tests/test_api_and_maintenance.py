import io
import zipfile

from fastapi.testclient import TestClient

from app import maintenance
from app.main import app
from app.security import mask_secrets

client = TestClient(app)


def test_health_and_case_crud():
    assert client.get("/health").json()["backend"] == "online"
    c = client.post("/cases", json={"title": "Erro X", "product": "GVcollege"}).json()
    assert client.get(f"/cases/{c['id']}").json()["title"] == "Erro X"
    assert client.patch(f"/cases/{c['id']}", json={"status": "Solucionado"}).json()["status"] == "Solucionado"
    assert client.get("/dashboard").json()["solved"] == 1
    assert client.get("/cases/99999").status_code == 404


def test_attachment_upload_extracts_text():
    c = client.post("/cases", json={"title": "Log"}).json()
    r = client.post(f"/cases/{c['id']}/attachments", files={"file": ("app.log", b"ERROR boom", "text/plain")})
    assert r.json()["has_text"]


def test_tools_endpoints():
    assert "INFORMATION_SCHEMA" in client.post("/tools/sql", json={"term": "nota"}).json()["code"]
    ps = client.post("/tools/powershell", json={"modules": ["iis", "rede"], "target": "PV990"}).json()
    assert ps["language"] == "powershell" and not ps["dangerous"]
    assert client.post("/tools/classify", json={"language": "sql", "code": "DROP TABLE x"}).json()["dangerous"]
    log = client.post("/tools/log", data={"text": "2026-01-01 10:00:00 ERROR boom"}).json()
    assert log["result"]["errors"] == 1
    cmp = client.post("/tools/compare", json={"a": "x\ny", "b": "x\nz"}).json()
    assert cmp["added"] == 1 and cmp["removed"] == 1


def test_local_execution_is_disabled_by_default():
    r = client.post("/tools/execute", json={"script": "Get-Service"})
    assert r.status_code == 403


def test_token_middleware(monkeypatch):
    import app.main as m

    monkeypatch.setattr(m, "API_TOKEN", "abc")
    assert client.get("/cases").status_code == 401
    assert client.get("/cases", headers={"x-gv-token": "abc"}).status_code == 200
    assert client.get("/health").status_code == 200


def test_masking():
    text = "Server=db;User Id=sa;Password=s3cr3t;Bearer abc.def token=xyz sk-abcdefghijklmnopqrstu"
    out = mask_secrets(text)
    for s in ("s3cr3t", "abc.def", "xyz", "sk-abcdefghijklmnopqrstu"):
        assert s not in out


def test_backup_roundtrip_without_secrets(tmp_path):
    client.post("/cases", json={"title": "Antes do backup"})
    path = maintenance.export_backup(tmp_path)
    with zipfile.ZipFile(path) as zf:
        assert {"gv_support_ai.db", "manifest.json"} <= set(zf.namelist())
    client.post("/cases", json={"title": "Depois do backup"})
    maintenance.import_backup(path)
    titles = [c["title"] for c in client.get("/cases").json()]
    assert titles == ["Antes do backup"]


def test_backup_import_rejects_foreign_zip(tmp_path):
    bad = tmp_path / "x.zip"
    with zipfile.ZipFile(bad, "w") as zf:
        zf.writestr("x.txt", "x")
    assert client.post("/backup/import", json={"path": str(bad)}).status_code == 400


def test_update_version_compare():
    assert maintenance._ver("v1.2.10") > maintenance._ver("1.2.9")
