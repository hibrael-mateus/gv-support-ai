import os
import sys
import tempfile
from pathlib import Path

# Isolated data dir per test session; must be set before `app` is imported.
os.environ["GV_SUPPORT_DATA_DIR"] = tempfile.mkdtemp(prefix="gvsupport-test-")
os.environ.pop("GV_API_TOKEN", None)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest  # noqa: E402

ALLOWED = "1RMbftBX58SM2PblBpw8vVaRoBF8sK_3c"


@pytest.fixture(autouse=True)
def clean_db():
    from app import db

    db.reset_for_tests()
    if db.DB_PATH.exists():
        db.DB_PATH.unlink()
    for suffix in ("-wal", "-shm"):
        p = Path(str(db.DB_PATH) + suffix)
        if p.exists():
            p.unlink()
    yield


class FakeProvider:
    """Deterministic stand-in for an LLM."""

    name = "fake"

    def __init__(self, chat_reply="", json_reply=None, online=True):
        self.chat_reply = chat_reply
        self.json_reply = json_reply or {}
        self._online = online
        self.prompts = []

    def status(self):
        return {"online": self._online, "models": ["fake"], "model": "fake"}

    def list_models(self):
        return ["fake"]

    def chat(self, messages, json_mode=False):
        self.prompts.append(messages)
        return self.chat_reply

    def chat_json(self, messages):
        self.prompts.append(messages)
        return self.json_reply

    def embed(self, texts):
        return None


def graph_lookup(graph):
    return lambda item: graph.get(item, [])


def index_sample(name, text, file_id="doc-1", path="/Fontes/GVcollege"):
    from app import rag

    graph = {file_id: ["sub"], "sub": [ALLOWED]}
    return rag.index_document(drive_file_id=file_id, name=name, pages=[(1, text)], parents_lookup=graph_lookup(graph),
                              path=path, modified_time="2026-09-01T10:00:00Z")
