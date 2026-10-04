# Manual de configuração

O assistente de configuração (7 etapas) cobre tudo abaixo. Ele pode ser reaberto em Configurações → Geral.

## 1. Inteligência artificial

Configurações → **IA**.

| Provedor | Quando usar | O que informar |
|---|---|---|
| Ollama (padrão) | Dados não saem do computador | Endereço (padrão `http://127.0.0.1:11434`), modelo de chat, `nomic-embed-text` |
| OpenAI compatível | Endpoint corporativo compatível com OpenAI | URL base, chave de API |
| Gemini / Groq | Nuvem, se a política da empresa permitir | Chave de API |
| Personalizado | Outro servidor compatível com OpenAI | URL base, chave |

As chaves ficam no Gerenciador de Credenciais do Windows. Use **Testar IA** para validar chat e embeddings.

## 2. Google Drive (fontes de conhecimento)

O programa lê somente a pasta **Fontes do Notebook LM** (`1RMbftBX58SM2PblBpw8vVaRoBF8sK_3c`) e suas subpastas,
com permissão só de leitura. Qualquer arquivo fora dela é rejeitado pelo programa.

### Criar o cliente OAuth (uma vez, pela TI ou pelo responsável)

1. Acesse <https://console.cloud.google.com/> e crie (ou escolha) um projeto.
2. **APIs e serviços → Biblioteca → Google Drive API → Ativar.**
3. **Tela de consentimento OAuth**: tipo *Interno* (Google Workspace) ou *Externo* em modo teste com os usuários adicionados.
   Escopo: `.../auth/drive.readonly`.
4. **Credenciais → Criar credenciais → ID do cliente OAuth → Tipo: App para computador.**
5. Baixe o JSON. Distribua-o aos analistas por canal interno; **não** coloque em repositório nem anexe em chamados.

### Conectar no app

Configurações → **Google Drive** → **Conectar Google Drive** → selecione o JSON → faça login no navegador que abrir.
O token fica no Gerenciador de Credenciais (`GVSupportAI / google_oauth_token`).

## 3. Indexar as fontes

Tela **Fontes** → **Sincronizar agora**. A primeira vez baixa e indexa tudo; depois só o que mudou
(novos, alterados, removidos). **Reindexar** apaga o índice e refaz. **Ver erros** lista arquivos que falharam.
Sincronização automática: Configurações → Geral.

Formatos: PDF, DOCX, XLSX, ZIP (conteúdo interno), CSV, TXT/LOG/SQL/PS1/JSON/XML/MD e Google Docs/Sheets/Slides (exportados).

## 4. Demais opções

| Categoria | Opções |
|---|---|
| Aparência | Claro, escuro ou igual ao Windows |
| Fontes | Tamanho do trecho (exige Reindexar) |
| Internet | Pesquisa auxiliar no Microsoft Learn (Windows, SQL Server, IIS…); nunca para objetos GV Dasa |
| Privacidade | Execução local de scripts de diagnóstico (desligada por padrão), backup e restauração |
| Atualizações | Verificar nova versão |
| Diagnóstico | Status de IA, Drive, RAG, índice, internet e backend; pasta de logs |

## Atalhos

Ctrl+N novo chamado · Ctrl+K pesquisa geral · Ctrl+L limpar o chat · Ctrl+Enter enviar · Ctrl+, configurações.

## Variáveis de ambiente (avançado)

Veja `.env.example`. `ALLOWED_GOOGLE_DRIVE_FOLDER_ID` só deve ser alterada por decisão formal da coordenação.
