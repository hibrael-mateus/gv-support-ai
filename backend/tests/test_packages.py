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


def test_stats_count_kis_and_tickets_inside_packages():
    _index()
    by_type = rag.stats()["by_type"]
    assert by_type.get("KI") == 1 and by_type.get("Chamado") == 1


COLLECTION = """# Coleção de KIs — Portal do Aluno 2.0

Documento gerado automaticamente a partir do TOPdesk.

---

## Sem título

**Número da KI:** Não informado

### Conteúdo

Sem conteúdo

---# Portal do Aluno 2.0 - Impressão de boletim

- **Número da KI:** KI 4694
- **Módulo:** Não informado

---

## 1. Descrição e Objetivo

Para imprimir o boletim no Portal do Aluno 2.0 o responsável acessa Boletim e clica em Imprimir; o modelo vem do parâmetro.

## 2. Procedimento, Regras e Informações da KI

O botão só aparece com a etapa fechada.
"""

FAQ = """# Perguntas frequentes — Portal do Professor 2.0

FAQs produzidas a partir de chamados encerrados do TOPdesk.

---

**Chamado:** 2609-1466

## Por que a nota de recuperação aparece no diário dos outros professores do grupo?

Quando as disciplinas estão no mesmo grupo, a recuperação fica associada ao grupo inteiro e aparece para todos.

**Produto:** Portal do Professor 2.0

---
"""


def test_standalone_collections_split_per_ki_and_ticket_even_with_glued_headings():
    kis = split_package(COLLECTION)
    assert [p[2]["title"] for p in kis] == ["KI 4694 · Portal do Aluno 2.0 - Impressão de boletim"]
    assert "etapa fechada" in kis[0][1]  # the KI keeps its "## 2." section
    faq = split_package(FAQ)
    assert faq[0][2]["doc_type"] == "Chamado"
    assert faq[0][2]["title"].startswith("Chamado 2609-1466 (Portal do Professor 2.0): Por que a nota")


def test_packaged_faq_with_chamado_markers_is_not_dropped():
    package = "<!-- AI-READY-PACKAGE v12 -->\n\n## Fonte: Perguntas frequentes — Portal do Professor 2.0\n\n" \
              + FAQ.replace("## Por que", "#### Por que") + "\n(Fim da fonte: Perguntas frequentes — Portal do Professor 2.0)\n"
    pages = split_package(package)
    assert len(pages) == 1 and "recuperação" in pages[0][1]


def test_sync_skips_old_copies_indexes_and_markers():
    from app.drive import SKIP

    assert SKIP.search("/Fontes Originais/Fontes/bkp/gvcollege/FAQ.md") and SKIP.search("/Fontes/GVcollege/_INDICE_GVcollege.md")
    assert SKIP.search("/Fontes/_AI_READY_SYNC_V14.marker") and not SKIP.search("/Fontes/GVcollege/GVcollege_001.md")
