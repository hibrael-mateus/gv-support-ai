import { useEffect, useState } from "react";
import {
  Box, Button, Card, CardContent, CardHeader, List, ListItemButton, ListItemText, Skeleton, Stack, Typography,
} from "@mui/material";
import AssignmentOutlinedIcon from "@mui/icons-material/AssignmentOutlined";
import ManageSearchIcon from "@mui/icons-material/ManageSearch";
import TaskAltIcon from "@mui/icons-material/TaskAlt";
import MoveUpIcon from "@mui/icons-material/MoveUp";
import LibraryBooksOutlinedIcon from "@mui/icons-material/LibraryBooksOutlined";
import SyncIcon from "@mui/icons-material/Sync";
import PsychologyOutlinedIcon from "@mui/icons-material/PsychologyOutlined";
import AddIcon from "@mui/icons-material/Add";
import { api } from "../api";
import { CaseStatusChip, PageHeader, StatCard, formatDate } from "../components/common";
import { errorText } from "../components/notify";
import type { Nav } from "../App";

type Data = Awaited<ReturnType<typeof api.dashboard>>;

export default function Dashboard({ go }: { go: Nav }) {
  const [data, setData] = useState<Data | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    api.dashboard().then(setData).catch((e) => setError(errorText(e)));
  }, []);

  const stats = data
    ? [
        { label: "Chamados investigados", value: data.investigated, icon: <AssignmentOutlinedIcon /> },
        { label: "Em investigação", value: data.in_progress, icon: <ManageSearchIcon /> },
        { label: "Solucionados", value: data.solved, icon: <TaskAltIcon /> },
        { label: "Escalonados N3", value: data.escalated, icon: <MoveUpIcon /> },
        { label: "Fontes disponíveis", value: data.sources, icon: <LibraryBooksOutlinedIcon /> },
        { label: "Última sincronização", value: data.last_sync ? formatDate(data.last_sync) : "Nunca", icon: <SyncIcon /> },
        { label: "Status da IA", value: data.ai.online ? "Online" : "Offline", icon: <PsychologyOutlinedIcon />, hint: data.ai.model || data.ai.provider },
      ]
    : [];

  return (
    <Box>
      <PageHeader
        title="Visão geral"
        subtitle="Acompanhe as investigações e a base de conhecimento GV Dasa."
        actions={<Button variant="contained" startIcon={<AddIcon />} onClick={() => go({ page: "new" })}>Novo chamado</Button>}
      />
      {error && <Typography color="error">{error}</Typography>}
      <Box sx={{ display: "grid", gap: 2, gridTemplateColumns: "repeat(auto-fill, minmax(200px, 1fr))", mb: 3 }}>
        {data ? stats.map((s) => <StatCard key={s.label} {...s} />) : Array.from({ length: 7 }, (_, i) => <Skeleton key={i} variant="rounded" height={78} />)}
      </Box>
      <Box sx={{ display: "grid", gap: 2, gridTemplateColumns: { xs: "1fr", lg: "repeat(3, minmax(0, 1fr))" } }}>
        <Card>
          <CardHeader title="Chamados recentes" slotProps={{ title: { variant: "subtitle1" } }} />
          <CardContent sx={{ pt: 0 }}>
            <List dense disablePadding>
              {data?.recent_cases.map((c) => (
                <ListItemButton key={c.id} onClick={() => go({ page: "case", id: c.id })} sx={{ borderRadius: 1 }}>
                  <ListItemText primary={`${c.number} · ${c.title}`} secondary={`${c.customer || "Sem cliente"} · ${formatDate(c.updated_at)}`}
                    slotProps={{ primary: { noWrap: true } }} />
                  <CaseStatusChip status={c.status} />
                </ListItemButton>
              ))}
              {data && !data.recent_cases.length && <Typography variant="body2" color="text.secondary">Nenhum chamado ainda.</Typography>}
            </List>
          </CardContent>
        </Card>
        <Card>
          <CardHeader title="Investigações recentes" slotProps={{ title: { variant: "subtitle1" } }} />
          <CardContent sx={{ pt: 0 }}>
            <List dense disablePadding>
              {data?.recent_investigations.map((c) => (
                <ListItemButton key={c.id} onClick={() => go({ page: "case", id: c.id })} sx={{ borderRadius: 1 }}>
                  <ListItemText primary={`${c.number} · ${c.title}`} secondary={c.last_message.replace(/[#*`>|]/g, "").slice(0, 110)}
                    slotProps={{ primary: { noWrap: true } }} />
                </ListItemButton>
              ))}
              {data && !data.recent_investigations.length && <Typography variant="body2" color="text.secondary">Nenhuma investigação em andamento.</Typography>}
            </List>
          </CardContent>
        </Card>
        <Card>
          <CardHeader title="Documentações mais utilizadas" slotProps={{ title: { variant: "subtitle1" } }} />
          <CardContent sx={{ pt: 0 }}>
            <List dense disablePadding>
              {data?.most_used.map((d) => (
                <ListItemButton key={d.drive_file_id} onClick={() => go({ page: "sources", query: d.name })} sx={{ borderRadius: 1 }}>
                  <ListItemText primary={d.name} secondary={`${d.uses} consulta(s)`} slotProps={{ primary: { noWrap: true } }} />
                </ListItemButton>
              ))}
              {data && !data.most_used.length && (
                <Stack spacing={1}>
                  <Typography variant="body2" color="text.secondary">As fontes mais consultadas aparecerão aqui.</Typography>
                  <Button size="small" variant="outlined" onClick={() => go({ page: "sources" })} sx={{ alignSelf: "flex-start" }}>Ir para Fontes</Button>
                </Stack>
              )}
            </List>
          </CardContent>
        </Card>
      </Box>
    </Box>
  );
}
