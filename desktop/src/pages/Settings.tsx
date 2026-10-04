import { useEffect, useState, type ReactNode } from "react";
import {
  Alert, Box, Button, Card, CardContent, Chip, FormControlLabel, List, ListItemButton, ListItemText, MenuItem, Stack, Switch,
  TextField, ToggleButton, ToggleButtonGroup, Typography,
} from "@mui/material";
import { api, type Settings as SettingsT, type SystemStatus } from "../api";
import { AiSection, DriveSection } from "../components/ConfigSections";
import { PageHeader, formatDate } from "../components/common";
import { errorText, useNotify } from "../components/notify";
import { openExternal, pickFile, revealPath } from "../native";
import type { Nav } from "../App";

const CATEGORIES = ["Geral", "Aparência", "IA", "Google Drive", "Fontes", "Banco vetorial", "Internet", "Privacidade", "Atualizações", "Diagnóstico", "Sobre"];

export function StatusPanel({ status }: { status: SystemStatus | null }) {
  const items: [string, boolean, string][] = status ? [
    ["IA", status.ai.online, status.ai.online ? status.ai.model || status.ai.provider : "offline"],
    ["Drive", status.drive.connected, status.drive.connected ? "conectado" : "desconectado"],
    ["RAG", status.rag.available, `${status.rag.documents} fontes`],
    ["Índice", !!status.index.last_sync, status.index.syncing ? "sincronizando" : status.index.last_sync ? formatDate(status.index.last_sync) : "vazio"],
    ["Internet", status.internet.enabled, status.internet.enabled ? "auxiliar ativa" : "desativada"],
    ["Backend", status.backend === "online", `v${status.version}`],
  ] : [];
  return (
    <Box sx={{ display: "grid", gap: 1, gridTemplateColumns: "repeat(auto-fill, minmax(170px, 1fr))" }}>
      {items.map(([k, ok, v]) => (
        <Box key={k} sx={{ border: 1, borderColor: "divider", borderRadius: 1, p: 1.25, display: "flex", alignItems: "center", gap: 1, bgcolor: "background.paper" }}>
          <Box sx={{ width: 10, height: 10, borderRadius: "50%", bgcolor: ok ? "success.main" : "error.main", flexShrink: 0 }} aria-hidden />
          <Box sx={{ minWidth: 0 }}>
            <Typography variant="body2" sx={{ fontWeight: 600 }}>{k}: {ok ? "OK" : "atenção"}</Typography>
            <Typography variant="caption" color="text.secondary" noWrap sx={{ display: "block" }}>{v}</Typography>
          </Box>
        </Box>
      ))}
    </Box>
  );
}

export default function Settings({ go, onSettings }: { go: Nav; onSettings: (s: SettingsT) => void }) {
  const notify = useNotify();
  const [cat, setCat] = useState(0);
  const [s, setS] = useState<SettingsT | null>(null);
  const [status, setStatus] = useState<SystemStatus | null>(null);
  const [update, setUpdate] = useState<Awaited<ReturnType<typeof api.updates>> | null>(null);
  const [logs, setLogs] = useState("");

  const reload = () => {
    api.settings().then(setS).catch((e) => notify(errorText(e), "error"));
    api.status().then(setStatus).catch(() => {});
  };
  useEffect(() => { reload(); }, []);
  useEffect(() => { if (s && !s.web) api.logsPath().then((r) => setLogs(r.path)).catch(() => {}); }, [s?.web]);

  const save = async (changes: Partial<SettingsT>) => {
    try {
      const next = { ...s!, ...(await api.saveSettings(changes)) };
      setS(next);
      onSettings(next);
      api.status().then(setStatus).catch(() => {});
    } catch (e) { notify(errorText(e), "error"); }
  };

  const exportBackup = async () => {
    try { const r = await api.backupExport(); notify(`Backup salvo em ${r.path}`); revealPath(r.path); } catch (e) { notify(errorText(e), "error"); }
  };
  const importBackup = async () => {
    const path = await pickFile(["zip"], "Selecione o backup do GV Support AI");
    if (!path || !window.confirm("Restaurar substitui chamados, histórico e configurações atuais. Um backup de segurança será criado antes. Continuar?")) return;
    try { const r = await api.backupImport(path); notify(`Backup restaurado. Cópia de segurança: ${r.safety_backup}`); reload(); } catch (e) { notify(errorText(e), "error"); }
  };

  if (!s) return <Typography color="text.secondary">Carregando…</Typography>;
  const section: Record<string, ReactNode> = {
    Geral: (
      <Stack spacing={2}>
        <TextField select label="Sincronização automática das fontes" value={s.auto_sync_minutes} onChange={(e) => save({ auto_sync_minutes: Number(e.target.value) })}>
          <MenuItem value={0}>Desativada (manual)</MenuItem>
          <MenuItem value={60}>A cada hora</MenuItem>
          <MenuItem value={240}>A cada 4 horas</MenuItem>
          <MenuItem value={1440}>Uma vez por dia</MenuItem>
        </TextField>
        <Button variant="outlined" sx={{ alignSelf: "flex-start" }} onClick={() => go({ page: "setup" })}>Abrir assistente de configuração</Button>
      </Stack>
    ),
    Aparência: (
      <Stack spacing={1}>
        <Typography variant="body2">Tema</Typography>
        <ToggleButtonGroup exclusive value={s.theme} onChange={(_, v) => v && save({ theme: v })} size="small" color="primary">
          <ToggleButton value="light">Claro</ToggleButton>
          <ToggleButton value="dark">Escuro</ToggleButton>
          <ToggleButton value="system">Sistema</ToggleButton>
        </ToggleButtonGroup>
      </Stack>
    ),
    IA: s.web
      ? <Alert severity="info">IA do servidor: <strong>{status?.ai.model || status?.ai.provider}</strong> ({status?.ai.online ? "online" : status?.ai.error || "offline"}). Configurada pelo administrador do site.</Alert>
      : <AiSection settings={s} onSaved={(n) => { setS(n); onSettings(n); reload(); }} />,
    "Google Drive": s.web
      ? <Alert severity={status?.drive.connected ? "success" : "warning"}>Google Drive do servidor {status?.drive.connected ? "conectado" : "não conectado"}. Somente a pasta autorizada é indexada.</Alert>
      : <DriveSection status={status?.drive ?? null} onChange={reload} />,
    Fontes: (
      <Stack spacing={2}>
        <TextField type="number" label="Tamanho do trecho (caracteres)" value={s.chunk_size} onChange={(e) => setS({ ...s, chunk_size: Number(e.target.value) })}
          onBlur={() => save({ chunk_size: s.chunk_size })} helperText="Alterar exige Reindexar para valer nas fontes já indexadas." sx={{ maxWidth: 320 }} />
        <Button variant="outlined" sx={{ alignSelf: "flex-start" }} onClick={() => go({ page: "sources" })}>Ir para Fontes</Button>
      </Stack>
    ),
    "Banco vetorial": (
      <Stack spacing={1}>
        <Typography variant="body2">Armazenamento local SQLite (FTS5 + vetores). Busca híbrida: semântica + BM25 + metadados + reranqueamento.</Typography>
        <Typography variant="body2">Trechos indexados: <strong>{status?.rag.chunks ?? 0}</strong> · vetorizados: <strong>{status?.rag.vectorized_chunks ?? 0}</strong></Typography>
        <Typography variant="body2">Modelo de embeddings: <strong>{s.embedding_model}</strong></Typography>
      </Stack>
    ),
    Internet: (
      <Stack spacing={1}>
        <FormControlLabel control={<Switch checked={s.internet_enabled} onChange={(e) => save({ internet_enabled: e.target.checked })} />} label="Permitir pesquisa auxiliar na internet" />
        <Alert severity="info">Usada somente para tecnologias externas (Windows, SQL Server, IIS, .NET) no Microsoft Learn. Tabelas, colunas, procedures e regras GV Dasa nunca são pesquisadas na internet.</Alert>
      </Stack>
    ),
    Privacidade: s.web ? (
      <Typography variant="body2">Na versão web, scripts nunca são executados pelo servidor. Copie o script e rode no ambiente do cliente. As chaves e o acesso ao Drive ficam só nos segredos do servidor.</Typography>
    ) : (
      <Stack spacing={2}>
        <FormControlLabel control={<Switch checked={s.allow_local_execution} onChange={(e) => save({ allow_local_execution: e.target.checked })} />}
          label="Permitir executar scripts de diagnóstico neste computador" />
        <Typography variant="caption" color="text.secondary">Mesmo ativado, scripts destrutivos (DELETE, UPDATE, DROP, Stop-Service, Remove-Item…) nunca são executados pelo programa.</Typography>
        <Typography variant="body2">Credenciais ficam no Gerenciador de Credenciais do Windows. Logs mascaram senhas, tokens e connection strings. Backups não incluem segredos.</Typography>
        <Stack direction="row" spacing={1}>
          <Button variant="outlined" onClick={exportBackup}>Exportar backup</Button>
          <Button onClick={importBackup}>Importar backup</Button>
        </Stack>
      </Stack>
    ),
    Atualizações: (
      <Stack spacing={2}>
        <Button variant="outlined" sx={{ alignSelf: "flex-start" }} onClick={() => api.updates().then(setUpdate).catch((e) => notify(errorText(e), "error"))}>Verificar atualizações</Button>
        {update && (update.error ? <Alert severity="warning">{update.error}</Alert>
          : update.available ? (
            <Alert severity="success" action={<Button color="inherit" onClick={() => openExternal(update.url)}>Baixar</Button>}>
              Versão {update.latest} disponível (atual {update.current}). O instalador atualiza mantendo chamados e configurações.
            </Alert>
          ) : <Alert severity="info">Você está na versão mais recente ({update.current}).</Alert>)}
      </Stack>
    ),
    Diagnóstico: (
      <Stack spacing={1.5}>
        <StatusPanel status={status} />
        <Typography variant="body2">Dados: {status?.data_dir}</Typography>
        {!s.web && <Typography variant="body2">Logs: {logs}</Typography>}
        <Stack direction="row" spacing={1}>
          {!s.web && <Button variant="outlined" onClick={() => revealPath(logs)}>Abrir pasta de logs</Button>}
          <Button onClick={reload}>Atualizar status</Button>
        </Stack>
      </Stack>
    ),
    Sobre: (
      <Stack spacing={1}>
        <Typography variant="h6">GV Support AI</Typography>
        <Typography variant="body2">Versão {status?.version}</Typography>
        <Typography variant="body2" color="text.secondary">Agente desktop especialista em suporte GV Dasa. Conhecimento restrito à pasta autorizada do Google Drive.</Typography>
        <Chip label={`Pasta autorizada: ${s.allowed_folder_id}`} variant="outlined" sx={{ alignSelf: "flex-start" }} />
      </Stack>
    ),
  };

  return (
    <Box>
      <PageHeader title="Configurações" />
      <Box sx={{ mb: 2 }}><StatusPanel status={status} /></Box>
      <Box sx={{ display: "grid", gap: 2, gridTemplateColumns: { xs: "1fr", md: "220px minmax(0, 1fr)" }, alignItems: "start" }}>
        <Card>
          <List dense component="nav" aria-label="Categorias">
            {CATEGORIES.map((c, i) => (
              <ListItemButton key={c} selected={i === cat} onClick={() => setCat(i)}><ListItemText primary={c} /></ListItemButton>
            ))}
          </List>
        </Card>
        <Card>
          <CardContent>
            <Typography variant="subtitle1" sx={{ mb: 2 }}>{CATEGORIES[cat]}</Typography>
            {section[CATEGORIES[cat]]}
          </CardContent>
        </Card>
      </Box>
    </Box>
  );
}
