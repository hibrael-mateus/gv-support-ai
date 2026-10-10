# Versão site (sem instalar nada nos computadores)

O mesmo GV Support AI roda como site no plano gratuito do **Render**, com o **Claude** (Anthropic, pago por uso) como IA. Sem a chave da Anthropic, o site usa o **Google Gemini**, que é gratuito.
Os analistas só abrem o endereço e digitam a senha da equipe.

## O que o site faz diferente do programa

- Entrada com a **senha da equipe** (10 tentativas erradas bloqueiam o endereço por 15 minutos).
- O menu **Administração** (fontes e configurações) pede uma segunda senha, a de administrador. Lá é possível
  sincronizar o Drive, reindexar e **anexar arquivos MD, PDF, TXT ou DOCX** como novas fontes.
- Conversas e índice são **compartilhados** pela equipe.
- Nenhum script é executado no servidor; o analista copia e roda no ambiente do cliente.
- Chaves de IA e acesso ao Drive ficam só nas **variáveis secretas do Render**, nunca no código ou na tela.
- O plano grátis dorme após 15 minutos sem uso; o primeiro acesso depois disso leva cerca de 1 minuto.
- O disco do plano grátis é apagado quando o servidor dorme. Com `HF_TOKEN` preenchido, o banco é salvo a cada
  10 minutos num **dataset privado** do Hugging Face (`<usuario-hf>/gv-support-ai-data`, criado sozinho).
  Sem ele, o índice do Drive é refeito a cada subida, mas os arquivos enviados e as configurações se perdem.

## Configurar (uma vez)

1. **Chave do Gemini:** entre em aistudio.google.com/apikey com uma conta Google e clique em **Create API key**.
2. **Render:** crie a conta em render.com entrando com o GitHub e autorize o acesso ao repositório `gv-support-ai`.
3. No Render, clique em **New → Blueprint**, escolha o repositório `gv-support-ai` e preencha:

| Variável | Valor |
|---|---|
| `GV_WEB_PASSWORD` | Senha da equipe para entrar no site |
| `GV_ADMIN_PASSWORD` | Senha do menu Administração (diferente da senha da equipe) |
| `GV_SECRET_ANTHROPIC_API_KEY` | Chave do Claude: console.anthropic.com → **Billing** (cadastre um cartão) → **API Keys** → **Create Key** |
| `GV_SECRET_GEMINI_API_KEY` | A chave do passo 1 (usada enquanto a chave da Anthropic estiver vazia) |
| `GV_SECRET_GOOGLE_SERVICE_ACCOUNT` | JSON da conta de serviço do Google Cloud com a API Google Drive ativada |
| `HF_TOKEN` | Opcional (recomendado): token do Hugging Face com permissão de escrita, para guardar o banco |

4. Clique em **Apply**. A primeira publicação leva alguns minutos; o endereço aparece no topo da página do serviço
   (`https://gv-support-ai.onrender.com` ou parecido).

Compartilhe a pasta **Fontes do Notebook LM** com o e-mail da conta de serviço (`…@….iam.gserviceaccount.com`)
como **Leitor**. Se a política do Google Workspace bloquear contas externas, use a variável
`GV_SECRET_GOOGLE_OAUTH_TOKEN` (token OAuth de um usuário com acesso à pasta).

A cada push na branch `main`, o Render publica a nova versão sozinho (`render.yaml`).
O servidor indexa a pasta autorizada na primeira subida e a cada 4 horas.

## Outras opções

- **Hugging Face Spaces:** desde 2026 exige o plano PRO para servidores Docker. Com PRO, rode manualmente o workflow
  **Deploy website (Hugging Face Spaces)**; lá a IA pode rodar dentro do servidor (`AI_MODE=embedded`).
- **Modelo do Claude:** o padrão é o Claude Sonnet 5.5 (melhor qualidade, alguns centavos de dólar por pergunta).
  Para gastar menos, escolha o Claude Haiku 5.5 em Administração → Configurações → IA.
- **Outra IA:** troque `GV_CONFIG_LLM_PROVIDER` para `groq` (com `GV_SECRET_GROQ_API_KEY`) ou outro provedor da tela
  Configurações → IA do programa.
