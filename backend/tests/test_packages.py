from app import rag
from app.agents import GVSupportOrchestrator
from app.agents.base import NO_EVIDENCE
from app.agents.specialists import _field
from app.extract import split_package
from conftest import ALLOWED, FakeProvider, graph_lookup

PACKAGE = """# AI-READY-PACKAGE

## Fonte: COLECAO_KIS_E_MANUAIS_GVnfse.md
> Caminho: Fontes/SaaS

### Sem título
Sem título / Sem conteúdo

### GVNFSe - Sistema parou de funcionar
Número da KI: KI 0315
Quando o serviço BEX/DEP para, reinicie o serviço de integração da nota fiscal de serviço e reprocesse os RPS pendentes.

## Fonte: FAQ_CHAMADOS_GVpay.md
> Caminho: Fontes/Serviços

#### Solicitação do cliente
01/02/2026 10:00 [GMT-3] Fulano: Bom dia, pagamentos com cartão não estão sendo baixados no financeiro da escola.
#### Histórico técnico e tratativas
Ajustada a credencial da adquirente e reprocessada a conciliação; os títulos foram baixados.
Estamos aguardando seu retorno para encerrar.
Senha: Abc123secreta
"""


def _index():
    pages = split_package(PACKAGE)
    graph = {"pkg": [ALLOWED]}
    rag.index_document(drive_file_id="pkg", name="AI-READY-PACKAGE.md", pages=pages,
                       parents_lookup=graph_lookup(graph), path="/Fontes", modified_time="2026-09-01T10:00:00Z")
    return pages


def test_split_package_titles_placeholders_and_noise():
    pages = split_package(PACKAGE)
    titles = [p[2]["title"] for p in pages]
    assert titles[0] == "KI 0315 · GVNFSe - Sistema parou de funcionar"
    assert titles[1].startswith("Chamado TOPdesk (GVpay): pagamentos com cartão")
    assert len(pages) == 2  # "Sem título" placeholder skipped
    assert "aguardando seu retorno" not in pages[1][1]


def test_indexed_ticket_masks_passwords_and_exposes_solution():
    _index()
    hits = rag.search("pagamentos cartão GVpay não baixados", 3)
    content = hits[0].content
    assert "Abc123secreta" not in content
    assert "credencial da adquirente" in _field(content, ("solução",))


def test_absent_topic_and_db_object_get_no_evidence():
    _index()
    for q in ("Como configurar a catraca da portaria no GVcollege?",
              "Qual o nome da tabela de pagamentos do GVpay?"):
        assert GVSupportOrchestrator(FakeProvider()).chat(q)["message"]["content"].startswith(NO_EVIDENCE), q
