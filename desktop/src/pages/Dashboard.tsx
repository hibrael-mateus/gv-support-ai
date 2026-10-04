import { useEffect, useState } from "react";
import {
  Box, Button, Card, CardContent, CardHeader, List, ListItemButton, ListItemText, Skeleton, Stack, Typography,
} from "@mui/material";
import LibraryBooksOutlinedIcon from "@mui/icons-material/LibraryBooksOutlined";
import SyncIcon from "@mui/icons-material/Sync";
import PsychologyOutlinedIcon from "@mui/icons-material/PsychologyOutlined";
import ChatOutlinedIcon from "@mui/icons-material/ChatOutlined";
import { api } from "../api";
import { PageHeader, StatCard, formatDate } from "../components/common";
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
        { label: "Fontes disponíveis", value: data.sources, icon: <LibraryBooksOutlinedIcon /> },
        { label: "Última sincronização", value: data.last_sync ? formatDate(data.last_sync) : "Nunca", icon: <SyncIcon /> },
        { label: "Status da IA", value: data.ai.online ? "Online" : "Offline", icon: <PsychologyOutlinedIcon />, hint: data.ai.model || data.ai.provider },
      ]
    : [];

  return (
    <Box>
      <PageHeader
        title="Visão geral"
        subtitle="Pergunte à IA com base no conhecimento GV Dasa."
        actions={<Button variant="contained" startIcon={<ChatOutlinedIcon />} onClick={() => go({ page: "chat" })}>Abrir o chat</Button>}
      />
      {error && <Typography color="error">{error}</Typography>}
      <Box sx={{ display: "grid", gap: 2, gridTemplateColumns: "repeat(auto-fill, minmax(220px, 1fr))", mb: 3 }}>
        {data ? stats.map((s) => <StatCard key={s.label} {...s} />) : Array.from({ length: 3 }, (_, i) => <Skeleton key={i} variant="rounded" height={78} />)}
      </Box>
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
  );
}
