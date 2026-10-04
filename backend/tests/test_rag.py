from app import rag
from app.agents.specialists import DocumentationAgent
from app.extract import chunk_text, infer_metadata
from conftest import ALLOWED, graph_lookup, index_sample


def test_hybrid_search_finds_relevant_document_with_excerpt_and_page():
    index_sample("KI 3220 - GVcollege x Pergamum WEB",
                 "Introdução geral.\n\nPara integrar o Pergamum WEB, configure a URL do webservice no parâmetro de integração. "
                 "Após salvar, reinicie o pool do Portal.", file_id="ki3220")
    index_sample("Manual Portal do Professor", "O diário de classe é gerado pelo relatório do Portal do Professor.",
                 file_id="manual", path="/Fontes/GVcollege/Portal")
    hits = rag.search("integração pergamum webservice")
    assert hits[0].drive_file_id == "ki3220"
    assert hits[0].page == 1
    assert "Pergamum WEB" in hits[0].excerpt
    assert 0 < hits[0].relevance <= 100


def test_search_is_accent_insensitive():
    index_sample("FAQ Matrícula", "Erro de matrícula ao confirmar rematrícula online.", file_id="faq")
    assert rag.search("matricula rematricula")[0].drive_file_id == "faq"


def test_metadata_filters():
    index_sample("KI 1 - GVcollege", "boleto vencido", file_id="a", path="/Fontes/GVcollege")
    index_sample("Manual GVmobile", "boleto vencido", file_id="b", path="/Fontes/GVmobile")
    assert {h.drive_file_id for h in rag.search("boleto", product="GVmobile")} == {"b"}
    assert {h.drive_file_id for h in rag.search("boleto", doc_type="KI")} == {"a"}


def test_vector_search_contributes_when_embeddings_exist():
    def embed(texts):
        return [[1.0, 0.0] if "certificado" in t.lower() or "tls" in t.lower() else [0.0, 1.0] for t in texts]

    graph = {"cert": [ALLOWED], "other": [ALLOWED]}
    rag.index_document(drive_file_id="cert", name="Procedimento SSL", pages=[(0, "Renovar certificado do IIS")],
                       parents_lookup=graph_lookup(graph), embedder=embed)
    rag.index_document(drive_file_id="other", name="Outro", pages=[(0, "Cadastro de alunos")],
                       parents_lookup=graph_lookup(graph), embedder=embed)
    hits = rag.search("TLS expirado", embedder=embed)  # no lexical overlap with "certificado"
    assert hits and hits[0].drive_file_id == "cert"


def test_reindex_replaces_chunks_and_removal_cleans_fts():
    index_sample("Doc", "versao antiga palavraunica", file_id="d")
    index_sample("Doc", "versao nova", file_id="d")
    assert rag.search("palavraunica") == []
    rag.remove_document("d")
    assert rag.search("versao") == []


def test_chunking_and_metadata():
    chunks = chunk_text("Frase. " * 600, size=500, overlap=50)
    assert len(chunks) > 5 and all(len(c) <= 520 for c in chunks)
    meta = infer_metadata("KI 3220 - GVcollege x Pergamum WEB.pdf", "/Fontes/GVcollege/Biblioteca")
    assert meta == {"product": "GVcollege", "module": "Biblioteca", "doc_type": "KI"}


def test_documentation_agent_cites_sources():
    index_sample("KI 77 - Cálculo de notas", "O cálculo de notas usa a média ponderada definida na fórmula.", file_id="ki77")
    res = DocumentationAgent(None).run("cálculo de notas média")
    assert res.sources and res.sources[0]["drive_file_id"] == "ki77"
    assert "[F1] KI 77" in res.content
