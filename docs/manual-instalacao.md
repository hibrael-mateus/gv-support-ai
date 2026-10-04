# Manual de instalação

## Requisitos

- Windows 10 ou 11, 64 bits, 8 GB de RAM (16 GB recomendados para IA local).
- Microsoft Edge WebView2 (já incluso no Windows 10/11 atualizados; o instalador baixa se faltar).
- Para IA local: [Ollama para Windows](https://ollama.com/download/windows).
- Acesso, com sua conta Google, à pasta do Drive “Fontes do Notebook LM”.

## Instalar

1. Baixe `GVSupportAI-Setup.exe` (ou `GVSupportAI.msi`) do Release mais recente.
2. Execute e confirme a elevação (instala para todos os usuários em `C:\Program Files\GV Support AI`).
3. Na última tela, marque “Criar atalho na Área de Trabalho” se quiser e clique em **Concluir**.
4. Abra pelo Menu Iniciar → **GV Support AI**. Na primeira execução o assistente de configuração abre sozinho.

Instalação silenciosa (TI): `GVSupportAI-Setup.exe /S` ou `msiexec /i GVSupportAI.msi /qn`.

## IA local (recomendado)

```powershell
# depois de instalar o Ollama
ollama pull llama3.1:8b          # ou outro modelo de chat
ollama pull nomic-embed-text     # embeddings para a busca semântica
```

## Atualizar

Configurações → Atualizações → **Verificar atualizações** → **Baixar**, e execute o novo instalador.
Chamados, histórico, índice e configurações ficam em `%LOCALAPPDATA%\GVSupportAI` e são mantidos.

## Desinstalar

Configurações do Windows → Aplicativos → **GV Support AI** → Desinstalar.
Os dados do usuário permanecem em `%LOCALAPPDATA%\GVSupportAI`; apague a pasta para removê-los.
Para remover o login do Google e as chaves de API: Gerenciador de Credenciais → Credenciais do Windows → itens `GVSupportAI`.

## Problemas comuns

| Sintoma | Solução |
|---|---|
| “Não foi possível iniciar o serviço interno” | Feche e abra novamente; veja `%LOCALAPPDATA%\GVSupportAI\Logs\backend.log`. Antivírus pode estar bloqueando `gv-support-backend.exe`. |
| IA offline | Abra o Ollama (ícone na bandeja) e use **Testar IA** em Configurações → IA. |
| Login do Google não abre | Verifique se o navegador padrão está configurado; tente **Reconectar**. |
