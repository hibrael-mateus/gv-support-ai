import { useEffect, useState } from "react";
import {
  Alert, Box, Button, Card, CardContent, Chip, Dialog, DialogActions, DialogContent, DialogTitle, InputAdornment, LinearProgress,
  List, ListItem, ListItemText, MenuItem, Stack, TextField, Typography,
} from "@mui/material";
import SyncIcon from "@mui/icons-material/Sync";
import RefreshIcon from "@mui/icons-material/Refresh";
import SearchIcon from "@mui/icons-material/Search";
import ErrorOutlineIcon from "@mui/icons-material/ErrorOutlined";
import LibraryBooksOutlinedIcon from "@mui/icons-material/LibraryBooksOutlined";
import ArticleOutlinedIcon from "@mui/icons-material/ArticleOutlined";
import MenuBookOutlinedIcon from "@mui/icons-material/MenuBookOutlined";
import QuizOutlinedIcon from "@mui/icons-material/QuizOutlined";
import CodeIcon from "@mui/icons-material/Code";
import AssignmentOutlinedIcon from "@mui/icons-material/AssignmentOutlined";
import { api, pollJob, type Job, type Source } from "../api";
import { PageHeader, StatCard, formatDate } from "../components/common";
import { SourceList } from "../components/Sources";
import { errorText, useNotify } from "../components/notify";

type Stats = Awaited<ReturnType<typeof api.sourceStats>>;
const TYPES = ["KI", "Manual", "FAQ", "Script", "RTM", "Chamado", "Procedimento"];

export default function Sources({ initialQuery = "" }: { initialQuery?: string }) {
  const notify = useNotify();
  const [stats, setStats] = useState<Stats | null>(null);
  const [job, setJob] = useState<Job | null>(null);
  const [query, setQuery] = useState(initialQuery);
  const [docType, setDocType] = useState("");
  const [hits, setHits] = useState<Source[] | null>(null);
  const [searching, setSearching] = useState(false);
  const [errors, setErrors] = useState<{ id: number; name: string; error: string; created_at: string }[] | null>(null);

  const refresh = () => api.sourceStats().then(setStats).catch((e) => notify(errorText(e), "error"));
  const follow = async (j: Job) => {
    const done = await pollJob(j.id, setJob);
    refresh();
    if (done.state === "error") notify(done.error || "Falha na sincronização", "error");
    else notify(done.message || "Sincronização concluída");
  };

  useEffect(() => {
    refresh();
    api.latestJob("sync").then((j) => { if ("id" in j && j.state === "running") follow(j as Job); }).catch(() => {});
    if (initialQuery) search(initialQuery);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const sync = async (full: boolean) => {
    if (full && !window.confirm("Reindexar apaga o índice atual e processa todas as fontes novamente. Continuar?")) return;
    try { follow(await api.sync(full)); } catch (e) { notify(errorText(e), "error"); }
  };

  const search = async (q = query) => {
    if (!q.trim()) return;
    setSearching(true);
    try { setHits(await api.search(q.trim(), { doc_type: docType })); } catch (e) { notify(errorText(e), "error"); } finally { setSearching(false); }
  };

  const running = job?.state === "running";
  const t = stats?.by_type ?? {};
  const cards = stats ? [
    { label: "Fontes indexadas", value: stats.documents, icon: <LibraryBooksOutlinedIcon /> },
    { label: "KIs", value: t.KI ?? 0, icon: <ArticleOutlinedIcon /> },
    { label: "Manuais", value: t.Manual ?? 0, icon: <MenuBookOutlinedIcon /> },
    { label: "FAQs", value: t.FAQ ?? 0, icon: <QuizOutlinedIcon /> },
    { label: "Scripts", value: t.Script ?? 0, icon: <CodeIcon /> },
    { label: "RTMs", value: t.RTM ?? 0, icon: <AssignmentOutlinedIcon /> },
    { label: "Erros de indexação", value: stats.errors, icon: <ErrorOutlineIcon /> },
    { label: "Última sincronização", value: stats.last_sync ? formatDate(stats.last_sync) : "Nunca", icon: <SyncIcon />, hint: `${stats.chunks} trechos · ${stats.vectorized_chunks} vetorizados` },
  ] : [];

  return (
    <Box>
      <PageHeader
        title="Fontes"
        subtitle="Somente a pasta autorizada “Fontes do Notebook LM” no Google Drive (e subpastas) alimenta o conhecimento."
        actions={
          <>
            <Button variant="contained" startIcon={<SyncIcon />} onClick={() => sync(false)} disabled={running}>Sincronizar agora</Button>
            <Button variant="outlined" startIcon={<RefreshIcon />} onClick={() => sync(true)} disabled={running}>Reindexar</Button>
            <Button startIcon={<ErrorOutlineIcon />} onClick={() => api.sourceErrors().then(setErrors)}>Ver erros</Button>
          </>
        }
      />
      {job && (running || job.state === "error") && (
        <Card sx={{ mb: 2 }}>
          <CardContent>
            <Stack direction="row" spacing={1} sx={{ justifyContent: "space-between", mb: 1 }}>
              <Typography variant="body2" sx={{ fontWeight: 600 }}>{job.message || "Sincronizando…"}</Typography>
              <Typography variant="body2">{job.total ? `${job.done}/${job.total}` : ""}</Typography>
            </Stack>
            <LinearProgress variant={job.total ? "determinate" : "indeterminate"} value={job.percent} color={job.state === "error" ? "error" : "primary"} />
            {job.error && <Alert severity="error" sx={{ mt: 1 }}>{job.error}</Alert>}
          </CardContent>
        </Card>
      )}
      <Box sx={{ display: "grid", gap: 2, gridTemplateColumns: "repeat(auto-fill, minmax(190px, 1fr))", mb: 3 }}>
        {cards.map((c) => <StatCard key={c.label} {...c} />)}
      </Box>

      <Card>
        <CardContent>
          <Typography variant="subtitle1" sx={{ mb: 1.5 }}>Pesquisar fonte</Typography>
          <Stack direction="row" spacing={1} sx={{ mb: 1 }}>
            <TextField value={query} onChange={(e) => setQuery(e.target.value)} onKeyDown={(e) => e.key === "Enter" && search()}
              placeholder="Ex.: rematrícula bloqueada, parâmetro de média, erro ao gerar boleto"
              slotProps={{ input: { startAdornment: <InputAdornment position="start"><SearchIcon /></InputAdornment> } }} />
            <TextField select label="Tipo" value={docType} onChange={(e) => setDocType(e.target.value)} sx={{ width: 180, flexShrink: 0 }}>
              <MenuItem value="">Todos</MenuItem>
              {TYPES.map((x) => <MenuItem key={x} value={x}>{x}</MenuItem>)}
            </TextField>
            <Button variant="outlined" onClick={() => search()} loading={searching} sx={{ flexShrink: 0 }}>Pesquisar</Button>
          </Stack>
          {hits && !hits.length && (
            <Alert severity="info">Não encontrei evidência suficiente nas fontes GV Dasa disponíveis para confirmar essa informação.</Alert>
          )}
          {hits && <SourceList sources={hits} />}
          {stats && Object.keys(stats.by_product).length > 0 && !hits && (
            <Stack direction="row" spacing={1} sx={{ flexWrap: "wrap", rowGap: 1, mt: 1 }}>
              {Object.entries(stats.by_product).map(([p, n]) => <Chip key={p} label={`${p || "Sem produto"}: ${n}`} variant="outlined" />)}
            </Stack>
          )}
        </CardContent>
      </Card>

      <Dialog open={!!errors} onClose={() => setErrors(null)} maxWidth="md" fullWidth>
        <DialogTitle>Erros de indexação</DialogTitle>
        <DialogContent dividers>
          {!errors?.length && <Typography color="text.secondary">Nenhum erro registrado.</Typography>}
          <List dense>
            {errors?.map((e) => <ListItem key={e.id} divider><ListItemText primary={e.name} secondary={`${formatDate(e.created_at)} · ${e.error}`} /></ListItem>)}
          </List>
        </DialogContent>
        <DialogActions><Button variant="contained" onClick={() => setErrors(null)}>Fechar</Button></DialogActions>
      </Dialog>
    </Box>
  );
}
