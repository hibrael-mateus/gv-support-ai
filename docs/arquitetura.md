# Documentação técnica

## Visão geral

```
┌──────────────────────── GV Support AI.exe (Tauri 2) ────────────────────────┐
│  Janela WebView2: React + TypeScript + MUI (tema do Design System GV Dasa)   │
│        │ fetch http://127.0.0.1:<porta livre>  (header x-gv-token)          │
│        ▼                                                                    │
│  backend\gv-support-backend.exe  (PyInstaller onedir, sem console)          │
│  FastAPI ─ Orquestrador ─ Agentes ─ RAG híbrido ─ SQLite (%LOCALAPPDATA%)   │
└──────────────┬──────────────────────────────┬───────────────────────────────┘
               │ Google Drive API (readonly)  │ IA embutida (llama.cpp) / provedor
               ▼                              ▼
   Pasta "Fontes do Notebook LM"        LLM + embeddings
```

- **Shell** (`desktop/src-tauri/src/lib.rs`): escolhe porta livre e token aleatório por execução, inicia o backend
  oculto (`CREATE_NO_WINDOW`) com `GV_PORT`, `GV_API_TOKEN` e `GV_PARENT_PID`, expõe `backend_info` e
  `write_text_file` (grava `.ps1` com BOM para o PowerShell 5.1) e encerra o backend ao sair. Se a janela morrer
  sem encerrar, o backend percebe a saída do processo pai e termina sozinho.
- **Posição da janela**: plugin `window-state` salva tamanho/posição por monitor; se o monitor não existir mais,
  a janela é reposicionada em um monitor visível.
- **Backend** (`backend/app`): FastAPI em `127.0.0.1` apenas; todas as rotas exigem o token, exceto `/health`.

## Módulos do backend

| Arquivo | Responsabilidade |
|---|---|
| `settings.py` | Pastas de dados, `config.json`, segredos no Windows Credential Manager (`keyring`, serviço `GVSupportAI`) |
| `security.py` | Restrição de fonte por ancestralidade, mascaramento de segredos em logs, classificação de scripts perigosos |
| `db.py` | SQLite: casos, fatos, hipóteses, mensagens, anexos, feedback, fontes, trechos, FTS5 |
| `extract.py` | Texto de PDF (por página), DOCX (com tabelas), XLSX (aba = página), ZIP, CSV e texto; metadados (produto, módulo, tipo) |
| `rag.py` | Indexação e busca híbrida |
| `drive.py` | OAuth (App para computador, escopo `drive.readonly`), varredura recursiva, sincronização incremental |
| `llm.py` | `LLMProvider`: IA embutida (padrão), Ollama, OpenAI compatível, Gemini, Groq, Personalizado |
| `embedded.py` | Motor `llama-server` (llama.cpp, CPU) incluído no instalador; baixa o modelo GGUF uma vez com verificação SHA-256, inicia sob demanda em porta local com chave aleatória e morre junto com o backend (Job Object) |
| `agents/` | Orquestrador e agentes especialistas |
| `cases.py` | Chamados, memória do caso, hipóteses, histórico, painel |
| `internet.py` | Pesquisa auxiliar só no Microsoft Learn, bloqueando termos internos GV |
| `maintenance.py` | Atualizações (GitHub Releases), backup/restauração sem segredos, execução local opcional |
| `jobs.py` | Tarefas em segundo plano com progresso (sincronização, login do Google) |

## Restrição das fontes (crítico)

1. `ALLOWED_GOOGLE_DRIVE_FOLDER_ID` vem só de variável de ambiente (padrão `1RMbftBX58SM2PblBpw8vVaRoBF8sK_3c`),
   nunca da interface.
2. A sincronização parte dessa pasta, não segue atalhos e, para **cada** arquivo, sobe a cadeia de pais
   (`is_allowed_by_ancestry`, até 64 níveis, com proteção contra ciclos e múltiplos pais).
   Resultado `ACCEPTED_SOURCE` ou `REJECTED_SOURCE`; qualquer erro rejeita (fail-closed).
3. `rag.index_document` chama `enforce_allowed_source` de novo: nenhum caminho de código indexa sem a verificação.
4. Cada trecho grava `authorized_root`; a busca filtra por ele (defesa em profundidade).
5. Teste de regressão: `backend/tests/test_source_scope.py`.

## RAG híbrido

1. Extração por página → trechos de ~1200 caracteres com sobreposição de 200.
2. Embeddings opcionais (provedores que os oferecem, ex. `nomic-embed-text` no Ollama) guardados como `float32` no SQLite.
3. Busca: BM25 (FTS5, sem acentos) + similaridade de cosseno (numpy) + filtros de metadados,
   fundidos por Reciprocal Rank Fusion (k=60) e reranqueados por cobertura de termos, frase exata e produto.
   Relevância 0–100; abaixo de 30 o trecho não conta como evidência. Um resultado por arquivo e página.
4. Sem embeddings (IA offline) a busca continua só com BM25.

> ponytail: busca vetorial por força bruta; acima de ~200 mil trechos vale trocar por índice ANN.

## Agentes

| Agente | Função |
|---|---|
| GVSupportOrchestrator | Roteia a intenção (ações rápidas ou texto livre), mantém a memória do caso e consolida a resposta |
| DocumentationAgent | Busca nas fontes e responde citando `[F1]`, `[F2]`… |
| SQLAgent | Descoberta no catálogo (INFORMATION_SCHEMA, sys.*) → SELECT → análise → alteração em transação → validação; marca objetos não confirmados |
| PowerShellAgent | Um script único de diagnóstico (sistema, disco, serviços, processos, IIS, rede, SQL, eventos, certificados, tarefas, HTTP, logs) exportando TXT/CSV/JSON/LOG/ZIP |
| LogAnalysisAgent | Erro principal, erros consequentes, frequência, servidores, processos, intervalo de tempo |
| SimilarCaseAgent | Casos locais e KIs semelhantes com causa e solução anteriores |
| ValidationAgent | Remove citações inválidas, aplica a frase de falta de evidência, impede hipótese “Confirmada” sem evidência |
| CustomerResponseAgent | Resposta ao cliente em português, sem jargão interno |
| N3EscalationAgent | Modelo de escalonamento N3 com o que foi testado e as evidências |

Sem IA disponível, o orquestrador usa caminhos determinísticos (busca, scripts, análise de log, modelos de texto).

## Segurança

- Segredos: Windows Credential Manager. Nada em código, Git, executável ou `config.json`.
- Logs: `SecretMaskingFilter` mascara senha, pwd, token, API key, Bearer, cookies, connection strings.
- Scripts: `classify_sql` / `classify_powershell` ignoram comentários e strings e marcam DELETE, UPDATE, DROP, ALTER,
  TRUNCATE, MERGE, Stop/Restart-Service, Remove-Item etc. A interface exibe “SCRIPT PERIGOSO”.
- Execução local: desligada por padrão; mesmo ligada, scripts perigosos são recusados.
- Backup: exporta banco, configuração e anexos, nunca segredos; importação valida manifesto e integridade e cria cópia de segurança antes.

## Dados

`%LOCALAPPDATA%\GVSupportAI\` → `gv_support_ai.db`, `config.json`, `Cache\`, `Logs\backend.log` (rotativo),
`Attachments\`, `Backups\`. Nada mutável em `Program Files`.

## Testes

| Área | Onde |
|---|---|
| Restrição do Drive | `backend/tests/test_source_scope.py` |
| RAG e citações | `test_rag.py`, `test_anti_hallucination.py` |
| SQL / PowerShell | `test_sql_agent.py`, `test_powershell_agent.py` + parser real do PowerShell no CI |
| Casos, orquestrador | `test_cases_and_orchestrator.py` |
| API, atualização, backup | `test_api_and_maintenance.py` |
| Interface | `tests/ui_smoke.py` (Playwright, 1366×768 e 150% de escala, tema escuro) |
| Instalador | CI: instalação silenciosa, atalho, abertura do app, backend sobe e encerra, desinstalação |

## Build e atualização

- CI (`.github/workflows/build.yml`, `windows-latest`): testes → PyInstaller → `tauri build` (NSIS + MSI) → teste do instalador → artefatos.
- Tag `vX.Y.Z` (via `scripts/release.ps1`) publica um Release; o app consulta o último Release do repositório
  configurado e oferece o download. O instalador NSIS atualiza no lugar, mantendo os dados do usuário.
