# Versão site (sem instalar nada nos computadores)

O mesmo GV Support AI roda como site num servidor gratuito do **Hugging Face Spaces**
(CPU grátis: 2 vCPU, 16 GB de RAM). Os analistas só abrem o endereço e digitam a senha da equipe.

## O que o site faz diferente do programa

- Entrada com a **senha da equipe** (10 tentativas erradas bloqueiam o endereço por 15 minutos).
- Chamados, histórico e índice são **compartilhados** pela equipe.
- Nenhum script é executado no servidor; o analista copia e roda no ambiente do cliente.
- Chaves de IA e acesso ao Drive ficam só nos **segredos do servidor**, nunca no código ou na tela.
- O banco é salvo a cada 10 minutos num **dataset privado** do Hugging Face, porque o disco do plano grátis é apagado quando o servidor reinicia.
- O plano grátis dorme após 48 h sem uso; o primeiro acesso depois disso leva cerca de 1 minuto.

## IA do site

| `AI_MODE` | Como funciona |
|---|---|
| `groq` (padrão) | API gratuita da Groq, chave guardada só no servidor. Respostas em segundos, limite diário gratuito. A Groq não usa os dados para treino. |
| `embedded` | O próprio modelo (Qwen2.5) roda no servidor. Nada sai do servidor, mas cada resposta leva 1 a 2 minutos e atende uma pessoa por vez. |

## Configurar (uma vez)

No repositório do GitHub, em **Settings → Secrets and variables → Actions**:

| Tipo | Nome | Valor |
|---|---|---|
| Secret | `HF_TOKEN` | Token do Hugging Face com permissão de escrita (huggingface.co → Settings → Access Tokens) |
| Secret | `GV_WEB_PASSWORD` | Senha da equipe para entrar no site |
| Secret | `GROQ_API_KEY` | Opcional. Chave em console.groq.com → API Keys. Sem ela, a IA roda no próprio servidor (`embedded`). |
| Secret | `GOOGLE_SERVICE_ACCOUNT` | JSON da chave de uma conta de serviço do Google Cloud com a API Google Drive ativada |

Depois, compartilhe a pasta **Fontes do Notebook LM** com o e-mail da conta de serviço
(`…@….iam.gserviceaccount.com`) como **Leitor**. Se a política do Google Workspace bloquear
compartilhar com contas externas, use o segredo `GOOGLE_OAUTH_TOKEN` (token OAuth de um usuário com acesso à pasta).

A cada push na branch `main`, o workflow **Deploy website** publica o site em
`https://huggingface.co/spaces/<usuario-hf>/gv-support-ai` (endereço direto: `https://<usuario>-gv-support-ai.hf.space`).
O servidor indexa a pasta autorizada na primeira subida e a cada 4 horas.
