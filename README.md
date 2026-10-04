# GV Support AI

Aplicativo desktop para Windows 10/11 (x64) que ajuda analistas de suporte GV Dasa a investigar chamados:
abre o chamado, consulta as fontes oficiais, levanta hipóteses, gera scripts SQL e PowerShell seguros,
analisa logs e prepara a resposta ao cliente ou o escalonamento N3. Não é um chatbot genérico: toda
afirmação sobre produtos GV Dasa precisa vir de uma fonte da pasta autorizada, citada com trecho e página.

Também roda como **site**, sem instalar nada nos computadores: veja [docs/site-web.md](docs/site-web.md).

| Instalador | Onde |
|---|---|
| `GVSupportAI-Setup.exe` (recomendado) | Releases do GitHub ou artefato do workflow *Build Windows installer* |
| `GVSupportAI.msi` | Mesmo lugar, para distribuição por GPO/Intune |

Instala em `C:\Program Files\GV Support AI`, cria atalho no Menu Iniciar (e na Área de Trabalho, opcional),
desinstalador em *Aplicativos instalados*. Dados ficam em `%LOCALAPPDATA%\GVSupportAI` e sobrevivem a atualizações.

## Documentação

- [Manual de instalação](docs/manual-instalacao.md)
- [Manual de configuração](docs/manual-configuracao.md) (IA local, Google Drive, fontes)
- [Documentação técnica](docs/arquitetura.md) (arquitetura, agentes, RAG, segurança, testes, build)

## Estrutura

```
backend/        Python 3.12 + FastAPI: agentes, RAG híbrido, Google Drive, casos (SQLite)
  app/agents/   Orquestrador + Documentation, SQL, PowerShell, LogAnalysis, SimilarCase,
                Validation, CustomerResponse e N3Escalation
  tests/        pytest (restrição do Drive, RAG, citações, anti-alucinação, SQL, PowerShell, casos, update)
desktop/        Tauri 2 + React + TypeScript + MUI (Design System GV Dasa)
  src-tauri/    Shell nativo: inicia o backend oculto, porta livre, token por sessão
tests/          Teste de interface (Playwright)
scripts/        build.ps1 (build local), release.ps1 (nova versão), export_ps_samples.py (CI)
.github/        Workflow que testa e gera o instalador no Windows
```

## Desenvolvimento rápido

```powershell
python -m venv .venv; .venv\Scripts\pip install -r backend\requirements-dev.txt
cd backend; ..\.venv\Scripts\python run_backend.py      # backend em http://127.0.0.1:8765
cd desktop; npm ci; npm run dev                          # interface no navegador (http://localhost:5173)
cd desktop; npx tauri dev                                # ou a janela desktop real
```

Testes: `cd backend; python -m pytest -q` e, com a interface compilada, `python tests/ui_smoke.py`.

## Regras que o código garante (não só o prompt)

- Só arquivos da pasta do Drive `1RMbftBX58SM2PblBpw8vVaRoBF8sK_3c` e subpastas entram no índice
  (verificação de ancestralidade a cada arquivo, `ACCEPTED_SOURCE` / `REJECTED_SOURCE`, filtro repetido na busca).
- Sem evidência, a resposta é: *"Não encontrei evidência suficiente nas fontes GV Dasa disponíveis para confirmar essa informação."*
- Nenhum script destrutivo é executado pelo programa; SQL de alteração sai em transação com COMMIT/ROLLBACK comentados.
- Credenciais só no Gerenciador de Credenciais do Windows; logs mascaram senhas, tokens e connection strings.
