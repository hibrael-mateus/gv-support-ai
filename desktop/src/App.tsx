import { useCallback, useEffect, useMemo, useState } from "react";
import {
  AppBar, Box, Button, CircularProgress, CssBaseline, Dialog, DialogContent, Divider, IconButton, InputAdornment, List,
  ListItemButton, ListItemIcon, ListItemText, ListSubheader, Paper, Stack, TextField, ThemeProvider, Toolbar, Tooltip, Typography,
  useMediaQuery,
} from "@mui/material";
import DashboardOutlinedIcon from "@mui/icons-material/DashboardOutlined";
import ChatOutlinedIcon from "@mui/icons-material/ChatOutlined";
import LibraryBooksOutlinedIcon from "@mui/icons-material/LibraryBooksOutlined";
import BuildOutlinedIcon from "@mui/icons-material/BuildOutlined";
import AdminPanelSettingsOutlinedIcon from "@mui/icons-material/AdminPanelSettingsOutlined";
import SearchIcon from "@mui/icons-material/Search";
import DarkModeOutlinedIcon from "@mui/icons-material/DarkModeOutlined";
import LightModeOutlinedIcon from "@mui/icons-material/LightModeOutlined";
import { ApiError, api, setWebToken, waitForBackend, type Settings as SettingsT } from "./api";
import { buildTheme } from "./theme";
import Dashboard from "./pages/Dashboard";
import Chat from "./pages/Chat";
import Sources from "./pages/Sources";
import Tools from "./pages/Tools";
import Admin from "./pages/Admin";
import Setup from "./pages/Setup";
import logo from "./assets/gv-dasa-logo.png";

export type Route = { page: string; query?: string };
export type Nav = (target: Route) => void;

const NAV = [
  { page: "dashboard", label: "Visão geral", icon: <DashboardOutlinedIcon /> },
  { page: "chat", label: "Chat", icon: <ChatOutlinedIcon /> },
  { page: "sources", label: "Fontes", icon: <LibraryBooksOutlinedIcon /> },
  { page: "tools", label: "Ferramentas", icon: <BuildOutlinedIcon /> },
  { page: "admin", label: "Administração", icon: <AdminPanelSettingsOutlinedIcon />, shortcut: "Ctrl+," },
];
const SIDENAV = 232;

export default function App() {
  const prefersDark = useMediaQuery("(prefers-color-scheme: dark)");
  const [ready, setReady] = useState<"wait" | "ok" | "fail" | "login">("wait");
  const [settings, setSettings] = useState<SettingsT | null>(null);
  const [route, setRoute] = useState<Route>({ page: "dashboard" });
  const [palette, setPalette] = useState(false);
  const [filter, setFilter] = useState("");

  const mode = settings?.theme === "dark" || (settings?.theme !== "light" && prefersDark) ? "dark" : "light";
  const theme = useMemo(() => buildTheme(mode), [mode]);
  const go: Nav = useCallback((r) => setRoute(r), []);

  const boot = useCallback(async () => {
    setReady("wait");
    if (!(await waitForBackend())) return setReady("fail");
    try { setSettings(await api.settings()); setReady("ok"); } catch (e) { setReady(e instanceof ApiError && e.status === 401 ? "login" : "fail"); }
  }, []);
  useEffect(() => { boot(); }, [boot]);
  useEffect(() => {
    const onLogin = () => setReady("login");
    window.addEventListener("gv:login", onLogin);
    return () => window.removeEventListener("gv:login", onLogin);
  }, []);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (!(e.ctrlKey || e.metaKey)) return;
      const k = e.key.toLowerCase();
      if (k === "k") { e.preventDefault(); setPalette(true); }
      else if (k === ",") { e.preventDefault(); go({ page: "admin" }); }
      else if (k === "l") {
        e.preventDefault();
        if (route.page === "chat") window.dispatchEvent(new Event("gv:clear-chat"));
        else go({ page: "chat" });
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [go, route.page]);

  const saveTheme = async (theme: SettingsT["theme"]) => setSettings({ ...settings!, ...(await api.saveSettings({ theme })) });

  let content;
  if (ready === "login") {
    content = <Login onDone={boot} />;
  } else if (ready !== "ok" || !settings) {
    content = (
      <Stack sx={{ height: "100vh", alignItems: "center", justifyContent: "center", gap: 2 }}>
        {ready === "wait" ? <><CircularProgress /><Typography>Iniciando o GV Support AI…</Typography></> : (
          <>
            <Typography variant="h6">Não foi possível iniciar o serviço interno.</Typography>
            <Typography variant="body2" color="text.secondary">Feche e abra o programa novamente. Se persistir, consulte os logs em %LOCALAPPDATA%\GVSupportAI\Logs.</Typography>
            <Button variant="contained" onClick={boot}>Tentar novamente</Button>
          </>
        )}
      </Stack>
    );
  } else if (!settings.setup_completed || route.page === "setup") {
    content = <Box sx={{ height: "100vh", overflowY: "auto", px: 2 }}><Setup onDone={(s) => { setSettings(s); go({ page: "dashboard" }); }} /></Box>;
  } else {
    const page = {
      dashboard: <Dashboard go={go} />,
      chat: <Chat />,
      sources: <Sources key={route.query} initialQuery={route.query} />,
      tools: <Tools go={go} />,
      admin: <Admin settings={settings} onSettings={setSettings} go={go} />,
    }[route.page] ?? <Dashboard go={go} />;
    const fullHeight = route.page === "chat";
    const items = NAV.filter((n) => n.label.toLowerCase().includes(filter.toLowerCase()));
    content = (
      <Box sx={{ display: "flex", flexDirection: "column", height: "100vh" }}>
        <AppBar position="static" color="primary">
          <Toolbar variant="dense" sx={{ gap: 1 }}>
            <Box component="img" src={logo} alt="GV Dasa" sx={{ height: 24 }} />
            <Typography variant="subtitle1" component="div" sx={{ flex: 1, fontWeight: 600, pl: 1, ml: 0.5, borderLeft: "1px solid rgba(255,255,255,.4)" }}>Support AI</Typography>
            <Button color="inherit" startIcon={<SearchIcon />} onClick={() => setPalette(true)} sx={{ opacity: 0.9 }}>Pesquisar (Ctrl+K)</Button>
            <Tooltip title={mode === "dark" ? "Tema claro" : "Tema escuro"}>
              <IconButton color="inherit" aria-label="Alternar tema" onClick={() => saveTheme(mode === "dark" ? "light" : "dark")}>
                {mode === "dark" ? <LightModeOutlinedIcon /> : <DarkModeOutlinedIcon />}
              </IconButton>
            </Tooltip>
          </Toolbar>
        </AppBar>
        <Box sx={{ display: "flex", flex: 1, minHeight: 0 }}>
          <Box component="nav" aria-label="Navegação principal"
            sx={{ width: SIDENAV, flexShrink: 0, bgcolor: mode === "dark" ? "#0f2b2a" : "primary.dark", color: "#fff", display: "flex", flexDirection: "column", overflowY: "auto" }}>
            <Box sx={{ p: 1.5 }}>
              <TextField size="small" placeholder="Buscar no menu" value={filter} onChange={(e) => setFilter(e.target.value)}
                slotProps={{
                  input: { startAdornment: <InputAdornment position="start"><SearchIcon sx={{ color: "rgba(255,255,255,.7)" }} /></InputAdornment>, sx: { color: "#fff", bgcolor: "rgba(255,255,255,.12)", "& fieldset": { border: 0 } } },
                  htmlInput: { "aria-label": "Buscar no menu" },
                }} />
            </Box>
            <List dense sx={{ px: 1 }}>
              {items.map((n) => {
                const selected = route.page === n.page;
                return (
                  <ListItemButton key={n.page} selected={selected} onClick={() => go({ page: n.page })}
                    sx={{ borderRadius: 1, mb: 0.25, color: "#fff", "&.Mui-selected, &.Mui-selected:hover": { bgcolor: "primary.light" }, "&:hover": { bgcolor: "rgba(255,255,255,.08)" } }}>
                    <ListItemIcon sx={{ color: "inherit", minWidth: 36 }}>{n.icon}</ListItemIcon>
                    <ListItemText primary={n.label} />
                  </ListItemButton>
                );
              })}
            </List>
          </Box>
          <Box component="main" sx={{ flex: 1, minWidth: 0, overflowY: fullHeight ? "hidden" : "auto", p: { xs: 2, md: 3 }, display: "flex", flexDirection: "column" }}>
            <Box sx={{ flex: fullHeight ? 1 : "none", minHeight: 0, maxWidth: 1600, width: "100%", mx: "auto", display: "flex", flexDirection: "column" }}>{page}</Box>
          </Box>
        </Box>
        <CommandPalette open={palette} onClose={() => setPalette(false)} go={go} />
      </Box>
    );
  }

  return (
    <ThemeProvider theme={theme}>
      <CssBaseline />
      {content}
    </ThemeProvider>
  );
}

/** Ctrl+K: jump to a page or search the sources. */
function CommandPalette({ open, onClose, go }: { open: boolean; onClose: () => void; go: Nav }) {
  const [q, setQ] = useState("");
  useEffect(() => { if (!open) setQ(""); }, [open]);
  const pick = (r: Route) => { onClose(); go(r); };
  const pages = NAV.filter((n) => n.label.toLowerCase().includes(q.toLowerCase()));
  return (
    <Dialog open={open} onClose={onClose} fullWidth maxWidth="sm" slotProps={{ paper: { sx: { alignSelf: "flex-start", mt: 10 } } }}>
      <DialogContent sx={{ p: 1.5 }}>
        <TextField autoFocus placeholder="Ir para uma página ou pesquisar nas fontes…" value={q} onChange={(e) => setQ(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter" && q.trim()) pick({ page: "sources", query: q.trim() }); }}
          slotProps={{ input: { startAdornment: <InputAdornment position="start"><SearchIcon /></InputAdornment> } }} />
        <List dense sx={{ maxHeight: 420, overflowY: "auto" }}>
          {q.trim() && (
            <ListItemButton onClick={() => pick({ page: "sources", query: q.trim() })}>
              <ListItemIcon><LibraryBooksOutlinedIcon /></ListItemIcon>
              <ListItemText primary={`Pesquisar “${q.trim()}” nas fontes GV Dasa`} secondary="Enter" />
            </ListItemButton>
          )}
          {pages.length > 0 && <><Divider /><ListSubheader disableSticky>Páginas</ListSubheader></>}
          {pages.map((n) => (
            <ListItemButton key={n.page} onClick={() => pick({ page: n.page })}>
              <ListItemIcon>{n.icon}</ListItemIcon>
              <ListItemText primary={n.label} secondary={n.shortcut} />
            </ListItemButton>
          ))}
        </List>
      </DialogContent>
    </Dialog>
  );
}

/** Website only: the team password set by the server administrator. */
function Login({ onDone }: { onDone: () => void }) {
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    try { setWebToken((await api.login(password)).token); onDone(); } catch (err) { setError(err instanceof Error ? err.message : String(err)); setBusy(false); }
  };
  return (
    <Stack sx={{ minHeight: "100vh", alignItems: "center", justifyContent: "center", gap: 3, px: 2, bgcolor: "primary.dark" }}>
      <Box component="img" src={logo} alt="GV Dasa" sx={{ height: 48 }} />
      <Paper component="form" onSubmit={submit} sx={{ p: 3, width: "100%", maxWidth: 360, display: "flex", flexDirection: "column", gap: 2, alignItems: "center" }}>
        <Typography variant="h6" component="h1">GV Support AI</Typography>
        <TextField type="password" label="Senha da equipe" autoFocus value={password} onChange={(e) => setPassword(e.target.value)}
          error={!!error} helperText={error || " "} autoComplete="current-password" />
        <Button type="submit" variant="contained" loading={busy} disabled={!password}>Entrar</Button>
      </Paper>
    </Stack>
  );
}
