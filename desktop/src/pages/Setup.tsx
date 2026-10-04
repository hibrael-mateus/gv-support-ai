import { useEffect, useState } from "react";
import {
  Alert, Box, Button, Card, CardContent, LinearProgress, List, ListItem, ListItemIcon, ListItemText, Stack, Step, StepLabel, Stepper,
  TextField, Typography,
} from "@mui/material";
import CheckCircleIcon from "@mui/icons-material/CheckCircle";
import ErrorIcon from "@mui/icons-material/Error";
import { api, pollJob, type Job, type Settings, type Source, type SystemStatus } from "../api";
import { AiSection, DriveSection } from "../components/ConfigSections";
import { SourceList } from "../components/Sources";
import { errorText, useNotify } from "../components/notify";

const STEPS = ["Verificar requisitos", "Configurar IA", "Conectar Google Drive", "Validar pasta autorizada", "Criar índice", "Testar RAG", "Finalizar"];

export default function Setup({ onDone }: { onDone: (s: Settings) => void }) {
  const notify = useNotify();
  const [step, setStep] = useState(0);
  const [status, setStatus] = useState<SystemStatus | null>(null);
  const [settings, setSettings] = useState<Settings | null>(null);
  const [folder, setFolder] = useState<{ name: string; error?: string } | null>(null);
  const [job, setJob] = useState<Job | null>(null);
  const [query, setQuery] = useState("");
  const [hits, setHits] = useState<Source[] | null>(null);

  const reload = () => { api.status().then(setStatus).catch(() => {}); api.settings().then(setSettings).catch(() => {}); };
  useEffect(reload, [step]);
  useEffect(() => {
    if (step === 3) api.driveFolder().then((f) => setFolder({ name: f.name })).catch((e) => setFolder({ name: "", error: errorText(e) }));
  }, [step]);

  const index = async () => {
    try { await pollJob((await api.sync(false)).id, setJob); reload(); } catch (e) { notify(errorText(e), "error"); }
  };
  const finish = async () => {
    const s = await api.saveSettings({ setup_completed: true });
    onDone({ ...settings!, ...s });
  };

  const check = (ok: boolean, label: string, hint: string) => (
    <ListItem>
      <ListItemIcon>{ok ? <CheckCircleIcon color="success" /> : <ErrorIcon color="warning" />}</ListItemIcon>
      <ListItemText primary={label} secondary={hint} />
    </ListItem>
  );

  const body = [
    <List dense key="req">
      {check(!!status, "Serviço interno do GV Support AI", status ? `Versão ${status.version} em execução` : "Iniciando…")}
      {check(!!status?.data_dir, "Pasta de dados do usuário", status?.data_dir ?? "")}
      {check(!!status?.ai.online, "Motor de IA", status?.ai.online ? status.ai.model : status?.ai.error || "Configure no próximo passo.")}
      {check(true, "Windows 10/11 x64", "Requisito do instalador")}
    </List>,
    settings && <AiSection key="ai" settings={settings} onSaved={setSettings} />,
    <DriveSection key="drive" status={status?.drive ?? null} onChange={reload} />,
    <Stack key="folder" spacing={1.5}>
      {!folder && <LinearProgress />}
      {folder?.name && <Alert severity="success">Pasta encontrada: <strong>{folder.name}</strong>. Somente ela e suas subpastas serão indexadas.</Alert>}
      {folder?.error && <Alert severity="error">Não foi possível acessar a pasta autorizada: {folder.error}. Verifique se a conta conectada tem acesso a ela.</Alert>}
    </Stack>,
    <Stack key="index" spacing={1.5}>
      <Typography variant="body2">Baixa e indexa KIs, manuais, FAQs, scripts e RTMs da pasta autorizada. Pode levar alguns minutos na primeira vez; as próximas sincronizações são incrementais.</Typography>
      {job && <><LinearProgress variant={job.total ? "determinate" : "indeterminate"} value={job.percent} /><Typography variant="caption">{job.message}</Typography></>}
      {job?.state === "error" && <Alert severity="error">{job.error}</Alert>}
      {status?.rag.available && <Alert severity="success">{status.rag.documents} fontes e {status.rag.chunks} trechos indexados.</Alert>}
      <Button variant="contained" sx={{ alignSelf: "flex-start" }} onClick={index} disabled={job?.state === "running"}>Criar índice agora</Button>
    </Stack>,
    <Stack key="rag" spacing={1.5}>
      <Stack direction="row" spacing={1}>
        <TextField label="Pergunta de teste" placeholder="Ex.: como configurar rematrícula" value={query} onChange={(e) => setQuery(e.target.value)} />
        <Button variant="outlined" disabled={!query.trim()} onClick={() => api.search(query).then(setHits).catch((e) => notify(errorText(e), "error"))} sx={{ flexShrink: 0 }}>Testar</Button>
      </Stack>
      {hits && !hits.length && <Alert severity="warning">Não encontrei evidência suficiente nas fontes GV Dasa disponíveis para confirmar essa informação.</Alert>}
      {hits && <SourceList sources={hits.slice(0, 5)} />}
    </Stack>,
    <Stack key="end" spacing={1}>
      <Typography>Tudo pronto. Você pode ajustar estas opções depois em Configurações.</Typography>
      <Typography variant="body2" color="text.secondary">Atalhos: Ctrl+N novo chamado · Ctrl+K pesquisa · Ctrl+L limpar chat · Ctrl+Enter enviar · Ctrl+, configurações.</Typography>
    </Stack>,
  ][step];

  return (
    <Box sx={{ maxWidth: 960, mx: "auto", py: 2 }}>
      <Typography variant="h5" component="h1" gutterBottom>Configuração inicial</Typography>
      <LinearProgress variant="determinate" value={(step / (STEPS.length - 1)) * 100} sx={{ mb: 2, height: 6, borderRadius: 3 }} aria-label="Progresso da configuração" />
      <Stepper activeStep={step} alternativeLabel sx={{ mb: 3 }}>
        {STEPS.map((s) => <Step key={s}><StepLabel>{s}</StepLabel></Step>)}
      </Stepper>
      <Card><CardContent>
        <Typography variant="subtitle1" sx={{ mb: 2 }}>{step + 1}. {STEPS[step]}</Typography>
        {body}
      </CardContent></Card>
      <Stack direction="row" spacing={1} sx={{ mt: 2, justifyContent: "flex-end" }}>
        {step < STEPS.length - 1 && <Button onClick={finish}>Pular configuração</Button>}
        <Button disabled={step === 0} onClick={() => setStep(step - 1)}>Voltar</Button>
        {step < STEPS.length - 1
          ? <Button variant="contained" onClick={() => setStep(step + 1)}>Avançar</Button>
          : <Button variant="contained" onClick={finish}>Concluir</Button>}
      </Stack>
    </Box>
  );
}
