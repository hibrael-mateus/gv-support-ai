/** AI provider and Google Drive sections, shared by Configurações and the setup wizard. */
import { useEffect, useState } from "react";
import { Alert, Box, Button, Chip, LinearProgress, MenuItem, Slider, Stack, TextField, Typography } from "@mui/material";
import CheckCircleIcon from "@mui/icons-material/CheckCircle";
import { api, pollJob, type Job, type Settings, type SystemStatus } from "../api";
import { openExternal, pickFile } from "../native";
import { errorText, useNotify } from "./notify";

export const PROVIDERS = [
  { id: "embedded", label: "IA embutida (recomendado, não precisa instalar nada)", key: "" },
  { id: "ollama", label: "Ollama (instalado à parte)", key: "" },
  { id: "openai_compatible", label: "OpenAI compatível", key: "openai_api_key" },
  { id: "gemini", label: "Google Gemini", key: "gemini_api_key" },
  { id: "groq", label: "Groq", key: "groq_api_key" },
  { id: "custom", label: "Personalizado (endpoint OpenAI compatível)", key: "custom_api_key" },
];

export function AiSection({ settings, onSaved }: { settings: Settings; onSaved: (s: Settings) => void }) {
  const notify = useNotify();
  const [s, setS] = useState(settings);
  const [models, setModels] = useState<string[]>([]);
  const [key, setKey] = useState("");
  const [test, setTest] = useState<Awaited<ReturnType<typeof api.aiTest>> | null>(null);
  const [testing, setTesting] = useState(false);
  const provider = PROVIDERS.find((p) => p.id === s.llm_provider) ?? PROVIDERS[0];

  useEffect(() => setS(settings), [settings]);
  const refreshModels = () => api.aiModels().then((r) => setModels(r.models)).catch(() => setModels([]));
  useEffect(() => { refreshModels(); }, [settings.llm_provider, settings.ollama_url]);

  const save = async (changes: Partial<Settings>) => {
    try {
      const next = await api.saveSettings(changes);
      onSaved({ ...s, ...next });
      notify("Configurações salvas");
    } catch (e) { notify(errorText(e), "error"); }
  };
  const saveAll = async () => {
    if (key && provider.key) { await api.saveSecret(provider.key, key); setKey(""); }
    await save({ llm_provider: s.llm_provider, ollama_url: s.ollama_url, llm_model: s.llm_model, embedding_model: s.embedding_model,
                 openai_base_url: s.openai_base_url, custom_base_url: s.custom_base_url, temperature: s.temperature });
    refreshModels();
  };
  const runTest = async () => {
    setTesting(true);
    try { setTest(await api.aiTest()); } catch (e) { setTest({ ok: false, error: errorText(e) }); } finally { setTesting(false); }
  };

  return (
    <Stack spacing={2}>
      <TextField select label="Provedor de IA" value={s.llm_provider} onChange={(e) => setS({ ...s, llm_provider: e.target.value })}>
        {PROVIDERS.map((p) => <MenuItem key={p.id} value={p.id}>{p.label}</MenuItem>)}
      </TextField>
      {s.llm_provider === "ollama" && (
        <TextField label="Endereço do Ollama" value={s.ollama_url} onChange={(e) => setS({ ...s, ollama_url: e.target.value })} helperText="Padrão: http://127.0.0.1:11434. Nada sai do computador." />
      )}
      {s.llm_provider === "embedded" && <EmbeddedModel onChanged={(n) => { setS({ ...s, ...n }); onSaved({ ...s, ...n }); }} />}
      {s.llm_provider === "openai_compatible" && <TextField label="URL base" value={s.openai_base_url} onChange={(e) => setS({ ...s, openai_base_url: e.target.value })} />}
      {s.llm_provider === "custom" && <TextField label="URL base do endpoint" value={s.custom_base_url} onChange={(e) => setS({ ...s, custom_base_url: e.target.value })} />}
      {provider.key && (
        <TextField type="password" label={`Chave de API ${settings.secrets?.[provider.key] ? "(já configurada, deixe em branco para manter)" : ""}`} value={key}
          onChange={(e) => setKey(e.target.value)} autoComplete="off" helperText="Guardada no Gerenciador de Credenciais do Windows, nunca em arquivo." />
      )}
      {s.llm_provider !== "embedded" && <Box sx={{ display: "grid", gap: 2, gridTemplateColumns: { xs: "1fr", md: "1fr 1fr" } }}>
        <TextField select={models.length > 0} label="Modelo de chat" value={s.llm_model} onChange={(e) => setS({ ...s, llm_model: e.target.value })}
          helperText={models.length ? `${models.length} modelo(s) disponível(is)` : "Vazio = primeiro modelo instalado"}>
          <MenuItem value="">Automático</MenuItem>
          {models.map((m) => <MenuItem key={m} value={m}>{m}</MenuItem>)}
        </TextField>
        <TextField label="Modelo de embeddings" value={s.embedding_model} onChange={(e) => setS({ ...s, embedding_model: e.target.value })}
          helperText={s.llm_provider === "ollama" ? "ollama pull nomic-embed-text" : "Modelo de embeddings do provedor"} />
      </Box>}
      <Box>
        <Typography variant="body2" gutterBottom>Temperatura: {s.temperature}</Typography>
        <Slider value={s.temperature} min={0} max={1} step={0.1} onChange={(_, v) => setS({ ...s, temperature: v as number })} sx={{ maxWidth: 320 }} aria-label="Temperatura" />
      </Box>
      <Stack direction="row" spacing={1}>
        <Button variant="contained" onClick={saveAll}>Salvar</Button>
        <Button variant="outlined" onClick={runTest} loading={testing}>Testar IA</Button>
        {s.llm_provider === "ollama" && <Button onClick={() => openExternal("https://ollama.com/download/windows")}>Baixar Ollama</Button>}
      </Stack>
      {test && (test.ok
        ? <Alert severity="success">IA respondeu “{test.answer}” em {test.seconds}s com o modelo {test.model}. Embeddings {test.embeddings ? "funcionando" : "indisponíveis (a busca usará só BM25)"}.</Alert>
        : <Alert severity="error">{test.error}</Alert>)}
    </Stack>
  );
}

/** Model for the bundled engine: download from the catalog once, or import a .gguf for offline networks. */
function EmbeddedModel({ onChanged }: { onChanged: (s: Partial<Settings>) => void }) {
  const notify = useNotify();
  const [info, setInfo] = useState<Awaited<ReturnType<typeof api.aiEmbedded>> | null>(null);
  const [pick, setPick] = useState("");
  const [job, setJob] = useState<Job | null>(null);
  const load = () => api.aiEmbedded().then((i) => { setInfo(i); setPick((p) => p || i.selected); }).catch(() => {});
  useEffect(() => { load(); }, []);
  if (!info) return <LinearProgress />;
  const chosen = info.models.find((m) => m.key === pick);

  const useModel = async () => {
    if (chosen?.downloaded) { onChanged(await api.saveSettings({ llm_provider: "embedded", embedded_model: pick, embedded_model_path: "" })); load(); return; }
    try {
      const done = await pollJob((await api.aiDownloadModel(pick)).id, setJob);
      if (done.state === "error") notify(done.error, "error"); else notify("Modelo pronto. A IA já pode ser usada.");
      onChanged({ llm_provider: "embedded", embedded_model: pick, embedded_model_path: "" });
      load();
    } catch (e) { notify(errorText(e), "error"); }
  };
  const importModel = async () => {
    const path = await pickFile(["gguf"], "Selecione o arquivo do modelo (.gguf)");
    if (!path) return;
    try { onChanged(await api.aiImportModel(path)); load(); notify("Modelo importado"); } catch (e) { notify(errorText(e), "error"); }
  };

  return (
    <Stack spacing={1.5}>
      {!info.binary && <Alert severity="error">O motor de IA não foi encontrado nesta instalação. Reinstale o GV Support AI.</Alert>}
      <Typography variant="body2" color="text.secondary">
        A IA roda dentro do programa, neste computador. Nada é enviado para fora. O modelo é baixado uma única vez.
      </Typography>
      <TextField select label="Modelo" value={pick} onChange={(e) => setPick(e.target.value)}>
        {info.models.map((m) => <MenuItem key={m.key} value={m.key}>{m.label}{m.downloaded ? " · baixado" : ""}</MenuItem>)}
      </TextField>
      {info.custom_path && <Alert severity="info">Em uso: modelo importado {info.custom_path}</Alert>}
      {job?.state === "running" && <Box><LinearProgress variant={job.total ? "determinate" : "indeterminate"} value={job.percent} /><Typography variant="caption">{job.message}</Typography></Box>}
      <Stack direction="row" spacing={1}>
        <Button variant="contained" onClick={useModel} disabled={job?.state === "running" || !info.binary}>
          {chosen?.downloaded ? "Usar este modelo" : "Baixar modelo"}
        </Button>
        <Button onClick={importModel} disabled={job?.state === "running"}>Importar arquivo .gguf</Button>
      </Stack>
    </Stack>
  );
}

export function DriveSection({ status, onChange }: { status: SystemStatus["drive"] | null; onChange: () => void }) {
  const notify = useNotify();
  const [job, setJob] = useState<Job | null>(null);
  const connect = async () => {
    const path = await pickFile(["json"], "Selecione o JSON do cliente OAuth do Google (App para computador)");
    if (!path) return;
    try {
      const done = await pollJob((await api.driveConnect(path)).id, setJob);
      if (done.state === "error") notify(done.error, "error"); else notify("Google Drive conectado");
      onChange();
    } catch (e) { notify(errorText(e), "error"); }
  };
  const disconnect = async () => { await api.driveDisconnect(); onChange(); };
  return (
    <Stack spacing={2}>
      <Stack direction="row" spacing={1} sx={{ alignItems: "center" }}>
        <Typography variant="body2">Status:</Typography>
        {status?.connected ? <Chip color="success" icon={<CheckCircleIcon />} label="Conectado (somente leitura)" /> : <Chip label="Não conectado" />}
      </Stack>
      <Alert severity="info">
        Pasta autorizada: <strong>Fontes do Notebook LM</strong> ({status?.allowed_folder_id}). Arquivos fora dela e de suas subpastas são rejeitados pelo programa, mesmo que a conta tenha acesso.
      </Alert>
      {job?.state === "running" && <Box><Typography variant="body2">Conclua o login no navegador que foi aberto…</Typography><LinearProgress /></Box>}
      <Stack direction="row" spacing={1}>
        <Button variant="contained" onClick={connect} disabled={job?.state === "running"}>{status?.connected ? "Reconectar" : "Conectar Google Drive"}</Button>
        {status?.connected && <Button onClick={disconnect}>Desconectar</Button>}
      </Stack>
      {!status?.client_secret_configured && (
        <Typography variant="caption" color="text.secondary">
          É necessário um cliente OAuth do tipo “App para computador” (Google Cloud Console, API Google Drive ativada). Veja o Manual de configuração.
        </Typography>
      )}
    </Stack>
  );
}
