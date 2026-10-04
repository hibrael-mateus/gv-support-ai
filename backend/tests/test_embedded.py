import hashlib
import os
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

from app import embedded
from app.llm import get_provider

BLOB = b"GGUF" + b"\0" * 2000


def _serve(sha):
    class H(BaseHTTPRequestHandler):
        def do_GET(self):  # mimics Hugging Face: redirect carrying the LFS sha256, then the CDN file
            if self.path == "/resolve/m.gguf":
                self.send_response(302)
                self.send_header("Location", "/cdn/m.gguf")
                self.send_header("X-Linked-Etag", f'"{sha}"')
                self.send_header("X-Linked-Size", str(len(BLOB)))
                self.end_headers()
            else:
                self.send_response(200)
                self.send_header("Content-Length", str(len(BLOB)))
                self.end_headers()
                self.wfile.write(BLOB)

        def log_message(self, *a):
            pass

    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


@pytest.mark.parametrize("ok", [True, False])
def test_download_checks_published_sha256(ok, monkeypatch, tmp_path):
    srv = _serve(hashlib.sha256(BLOB).hexdigest() if ok else "0" * 64)
    url = f"http://127.0.0.1:{srv.server_port}/resolve/m.gguf"
    monkeypatch.setattr(embedded, "MODEL_DIR", tmp_path)
    monkeypatch.setitem(embedded.MODELS, "t", {"label": "t", "url": url})
    if ok:
        assert embedded.is_gguf(Path(embedded.download("t")))
    else:
        with pytest.raises(RuntimeError):
            embedded.download("t")
        assert not list(tmp_path.iterdir())  # no partial or bad file left behind
    srv.shutdown()


def test_missing_model_reports_how_to_fix(monkeypatch, tmp_path):
    monkeypatch.setattr(embedded, "MODEL_DIR", tmp_path)
    st = get_provider({"llm_provider": "embedded"}).status()
    assert not st["online"] and st["error"]


@pytest.mark.skipif(not os.getenv("GV_TEST_MODEL"), reason="needs GV_LLAMA_SERVER and a real GGUF in GV_TEST_MODEL")
def test_real_engine_answers():
    p = get_provider({"llm_provider": "embedded", "embedded_model_path": os.environ["GV_TEST_MODEL"]})
    assert p.status()["online"]
    answer = p.chat([{"role": "user", "content": "Responda apenas a palavra OK."}])
    embedded.stop()
    assert answer.strip()
