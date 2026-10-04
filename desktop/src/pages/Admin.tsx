import { useState } from "react";
import { Alert, Box, Button, Card, CardContent, Stack, Tab, Tabs, TextField, Typography } from "@mui/material";
import AdminPanelSettingsOutlinedIcon from "@mui/icons-material/AdminPanelSettingsOutlined";
import { api, setWebToken, type Settings as SettingsT } from "../api";
import { errorText } from "../components/notify";
import Sources from "./Sources";
import Settings from "./Settings";
import type { Nav } from "../App";

/** Everything that changes the tool for the whole team: sources and settings. On the website it needs the admin password. */
export default function Admin({ settings, onSettings, go }: { settings: SettingsT; onSettings: (s: SettingsT) => void; go: Nav }) {
  const [tab, setTab] = useState(0);
  if (!settings.admin) return <AdminLogin onDone={async () => onSettings(await api.settings())} />;
  return (
    <Box>
      <Tabs value={tab} onChange={(_, v) => setTab(v)} sx={{ mb: 2, borderBottom: 1, borderColor: "divider" }}>
        <Tab label="Fontes" />
        <Tab label="Configurações" />
      </Tabs>
      {tab === 0 ? <Sources admin /> : <Settings go={go} onSettings={onSettings} />}
    </Box>
  );
}

function AdminLogin({ onDone }: { onDone: () => Promise<void> }) {
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    try { setWebToken((await api.adminLogin(password)).token); await onDone(); } catch (err) { setError(errorText(err)); setBusy(false); }
  };
  return (
    <Card sx={{ maxWidth: 420, mx: "auto", mt: 6 }}>
      <CardContent component="form" onSubmit={submit}>
        <Stack spacing={2} sx={{ alignItems: "center", textAlign: "center" }}>
          <AdminPanelSettingsOutlinedIcon color="primary" sx={{ fontSize: 48 }} />
          <Typography variant="h6" component="h1">Administração</Typography>
          <Typography variant="body2" color="text.secondary">Gerencie as fontes e as configurações da ferramenta. Digite a senha de administrador.</Typography>
          <TextField type="password" label="Senha de administrador" autoFocus value={password} onChange={(e) => setPassword(e.target.value)}
            autoComplete="current-password" />
          {error && <Alert severity="error" sx={{ width: "100%" }}>{error}</Alert>}
          <Button type="submit" variant="contained" loading={busy} disabled={!password}>Entrar</Button>
        </Stack>
      </CardContent>
    </Card>
  );
}
