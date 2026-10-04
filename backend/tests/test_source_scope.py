"""CRITICAL: only documents inside the authorized Drive folder may enter the RAG."""
import pytest

from app import rag
from app.security import ACCEPTED_SOURCE, REJECTED_SOURCE, SourceRejectedError, classify_source, is_allowed_by_ancestry
from conftest import ALLOWED, graph_lookup


def test_document_inside_authorized_folder_is_accepted():
    graph = {"file-in": ["child-folder"], "child-folder": [ALLOWED], ALLOWED: ["root"]}
    assert classify_source("file-in", graph_lookup(graph), ALLOWED) == ACCEPTED_SOURCE


def test_document_outside_authorized_folder_is_rejected():
    graph = {"file-out": ["other-folder"], "other-folder": ["root"], ALLOWED: ["root"]}
    assert classify_source("file-out", graph_lookup(graph), ALLOWED) == REJECTED_SOURCE


def test_deeply_nested_subfolder_is_accepted():
    graph = {"f": ["a"], "a": ["b"], "b": ["c"], "c": ["d"], "d": [ALLOWED]}
    assert is_allowed_by_ancestry("f", graph_lookup(graph), ALLOWED)


def test_multiple_parents_one_authorized_is_accepted():
    graph = {"f": ["outside", "inside"], "outside": ["root"], "inside": [ALLOWED]}
    assert classify_source("f", graph_lookup(graph), ALLOWED) == ACCEPTED_SOURCE


def test_cycle_in_parent_graph_does_not_hang_and_is_rejected():
    graph = {"f": ["a"], "a": ["b"], "b": ["a"]}
    assert classify_source("f", graph_lookup(graph), ALLOWED) == REJECTED_SOURCE


def test_lookup_failure_fails_closed():
    def boom(_):
        raise RuntimeError("Drive API offline")

    assert classify_source("f", boom, ALLOWED) == REJECTED_SOURCE


def test_sibling_folder_with_similar_id_is_rejected():
    graph = {"f": [ALLOWED + "x"], ALLOWED + "x": ["root"]}
    assert classify_source("f", graph_lookup(graph), ALLOWED) == REJECTED_SOURCE


def test_index_document_refuses_outside_file_and_index_stays_empty():
    graph = {"evil": ["personal-folder"], "personal-folder": ["root"]}
    with pytest.raises(SourceRejectedError):
        rag.index_document(drive_file_id="evil", name="salarios.pdf", pages=[(1, "dados pessoais confidenciais")],
                           parents_lookup=graph_lookup(graph))
    assert rag.stats()["documents"] == 0
    assert rag.search("dados pessoais confidenciais") == []


def test_index_document_accepts_inside_file():
    graph = {"good": ["sub"], "sub": [ALLOWED]}
    n = rag.index_document(drive_file_id="good", name="KI 100 - Portal.pdf", pages=[(1, "conteúdo autorizado")],
                           parents_lookup=graph_lookup(graph))
    assert n == 1
    assert rag.stats()["documents"] == 1


def test_search_ignores_chunks_indexed_under_another_root():
    other = "OTHER_ROOT"
    graph = {"x": [other]}
    rag.index_document(drive_file_id="x", name="doc.txt", pages=[(0, "texto exclusivo zebra")],
                       parents_lookup=graph_lookup(graph), allowed_folder_id=other)
    assert rag.search("zebra") == []  # default search scope is the authorized folder only


class _FakeFiles:
    def __init__(self, tree, meta):
        self.tree, self.meta = tree, meta

    def list(self, q, **kw):
        folder = q.split("'")[1]
        return _Exec({"files": [self.meta[i] for i in self.tree.get(folder, [])]})

    def get(self, fileId, **kw):
        return _Exec(self.meta[fileId])

    def export(self, fileId, mimeType):
        return _Exec(self.meta[fileId]["_content"])


class _Exec:
    def __init__(self, data):
        self.data = data

    def execute(self):
        return self.data


class _FakeService:
    def __init__(self, files):
        self._files = files

    def files(self):
        return self._files


def test_drive_sync_indexes_only_authorized_tree_and_skips_shortcuts():
    from app import drive

    gdoc = "application/vnd.google-apps.document"
    meta = {
        ALLOWED: {"id": ALLOWED, "name": "Fontes", "mimeType": drive.FOLDER_MIME, "parents": ["root"]},
        "sub": {"id": "sub", "name": "GVcollege", "mimeType": drive.FOLDER_MIME, "parents": [ALLOWED]},
        "ki": {"id": "ki", "name": "KI 3220 - GVcollege x Pergamum WEB", "mimeType": gdoc, "parents": ["sub"],
               "modifiedTime": "2026-09-01T00:00:00Z", "_content": b"Integracao Pergamum WEB exige URL configurada."},
        "short": {"id": "short", "name": "atalho", "mimeType": drive.SHORTCUT_MIME, "parents": ["sub"]},
    }
    tree = {ALLOWED: ["sub"], "sub": ["ki", "short"]}
    gw = drive.GoogleDriveGateway(service=_FakeService(_FakeFiles(tree, meta)), allowed_folder_id=ALLOWED)
    counts = drive.sync(gateway=gw)
    assert counts["new"] == 1 and counts["rejected"] == 1
    hits = rag.search("Pergamum URL")
    assert hits and hits[0].source_name.startswith("KI 3220")
    assert hits[0].doc_type == "KI" and hits[0].product == "GVcollege"
    # incremental: second sync changes nothing
    assert drive.sync(gateway=gw)["unchanged"] == 1
    # removal: file disappears from Drive -> leaves the index
    tree["sub"] = ["short"]
    assert drive.sync(gateway=drive.GoogleDriveGateway(service=_FakeService(_FakeFiles(tree, meta)),
                                                       allowed_folder_id=ALLOWED))["removed"] == 1
    assert rag.stats()["documents"] == 0
