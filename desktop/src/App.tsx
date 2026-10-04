import { useCallback, useEffect, useMemo, useState } from "react";
import {
  AppBar, Box, Button, CircularProgress, CssBaseline, Dialog, DialogContent, Divider, IconButton, InputAdornment, List,
  ListItemButton, ListItemIcon, ListItemText, ListSubheader, Stack, TextField, ThemeProvider, Toolbar, Tooltip, Typography,
  useMediaQuery,
} from "@mui/material";
import DashboardOutlinedIcon from "@mui/icons-material/DashboardOutlined";
import AddCircleOutlineIcon from "@mui/icons-material/AddCircleOutlined";
import AssignmentOutlinedIcon from "@mui/icons-material/AssignmentOutlined";
import ChatOutlinedIcon from "@mui/icons-material/ChatOutlined";
import LibraryBooksOutlinedIcon from "@mui/icons-material/LibraryBooksOutlined";
import BuildOutlinedIcon from "@mui/icons-material/BuildOutlined";
import HistoryIcon from "@mui/icons-material/History";
import SettingsOutlinedIcon from "@mui/icons-material/SettingsOutlined";
import SearchIcon from "@mui/icons-material/Search";
import DarkModeOutlinedIcon from "@mui/icons-material/DarkModeOutlined";
import LightModeOutlinedIcon from "@mui/icons-material/LightModeOutlined";
import { api, waitForBackend, type Case, type Settings as SettingsT } from "./api";
import { buildTheme } from "./theme";
import Dashboard from "./pages/Dashboard";
import NewCase from "./pages/NewCase";
import Cases from "./pages/Cases";
import CaseView from "./pages/CaseView";
import Chat from "./pages/Chat";
import Sources from "./pages/Sources";
import Tools from "./pages/Tools";
import Settings from "./pages/Settings";
import Setup from "./pages/Setup";

export type Route = { page: string; id?: number; query?: string; autoInvestigate?: boolean };
export type Nav = (target: Route) => void;

const NAV = [
  { page: "dashboard", label: "Visão geral", icon: <DashboardOutlinedIcon /> },
  { page: "new", label: "Novo chamado", icon: <AddCircleOutlineIcon />, shortcut: "Ctrl+N" },
  { page: "cases", label: "Chamados", icon: <AssignmentOutlinedIcon /> },
  { page: "chat", label: "Chat", icon: <ChatOutlinedIcon /> },
  { page: "sources", label: "Fontes", icon: <LibraryBooksOutlinedIcon /> },
  { page: "tools", label: "Ferramentas", icon: <BuildOutlinedIcon /> },
  { page: "history", label: "Histórico", icon: <HistoryIcon /> },
  { page: "settings", label: "Configurações", icon: <SettingsOutlinedIcon />, shortcut: "Ctrl+," },
];
const SIDENAV = 232;

export default function App() {
  const prefersDark = useMediaQuery("(prefers-color-scheme: dark)");
  const [ready, setReady] = useState<"wait" | "ok" | "fail">("wait");
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
    try { setSettings(await api.settings()); setReady("ok"); } catch { setReady("fail"); }
  }, []);
  useEffect(() => { boot(); }, [boot]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (!(e.ctrlKey || e.metaKey)) return;
      const k = e.key.toLowerCase();
      if (k === "n") { e.preventDefault(); go({ page: "new" }); }
      else if (k === "k") { e.preventDefault(); setPalette(true); }
      else if (k === ",") { e.preventDefault(); go({ page: "settings" }); }
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
  if (ready !== "ok" || !settings) {
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
      new: <NewCase go={go} />,
      cases: <Cases go={go} />,
      history: <Cases go={go} history />,
      case: <CaseView key={route.id} id={route.id!} autoInvestigate={route.autoInvestigate} go={go} />,
      chat: <Chat />,
      sources: <Sources key={route.query} initialQuery={route.query} />,
      tools: <Tools go={go} />,
      settings: <Settings go={go} onSettings={setSettings} />,
    }[route.page] ?? <Dashboard go={go} />;
    const fullHeight = route.page === "case" || route.page === "chat";
    const items = NAV.filter((n) => n.label.toLowerCase().includes(filter.toLowerCase()));
    content = (
      <Box sx={{ display: "flex", flexDirection: "column", height: "100vh" }}>
        <AppBar position="static" color="primary">
          <Toolbar variant="dense" sx={{ gap: 1 }}>
            <Typography variant="subtitle1" component="div" sx={{ flex: 1 }}>GV Support AI</Typography>
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
                const selected = route.page === n.page || (n.page === "cases" && route.page === "case");
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

/** Ctrl+K: jump to a page, open a case or search the sources. */
function CommandPalette({ open, onClose, go }: { open: boolean; onClose: () => void; go: Nav }) {
  const [q, setQ] = useState("");
  const [cases, setCases] = useState<Case[]>([]);
  useEffect(() => { if (!open) setQ(""); }, [open]);
  useEffect(() => {
    if (!open || q.trim().length < 2) { setCases([]); return; }
    const t = setTimeout(() => api.cases("", q.trim()).then((r) => setCases(r.slice(0, 6))).catch(() => {}), 200);
    return () => clearTimeout(t);
  }, [q, open]);
  const pick = (r: Route) => { onClose(); go(r); };
  const pages = NAV.filter((n) => n.label.toLowerCase().includes(q.toLowerCase()));
  return (
    <Dialog open={open} onClose={onClose} fullWidth maxWidth="sm" slotProps={{ paper: { sx: { alignSelf: "flex-start", mt: 10 } } }}>
      <DialogContent sx={{ p: 1.5 }}>
        <TextField autoFocus placeholder="Ir para, buscar chamado ou pesquisar nas fontes…" value={q} onChange={(e) => setQ(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter" && q.trim()) pick({ page: "sources", query: q.trim() }); }}
          slotProps={{ input: { startAdornment: <InputAdornment position="start"><SearchIcon /></InputAdornment> } }} />
        <List dense sx={{ maxHeight: 420, overflowY: "auto" }}>
          {q.trim() && (
            <ListItemButton onClick={() => pick({ page: "sources", query: q.trim() })}>
              <ListItemIcon><LibraryBooksOutlinedIcon /></ListItemIcon>
              <ListItemText primary={`Pesquisar “${q.trim()}” nas fontes GV Dasa`} secondary="Enter" />
            </ListItemButton>
          )}
          {cases.length > 0 && <><Divider /><ListSubheader disableSticky>Chamados</ListSubheader></>}
          {cases.map((c) => (
            <ListItemButton key={c.id} onClick={() => pick({ page: "case", id: c.id })}>
              <ListItemIcon><AssignmentOutlinedIcon /></ListItemIcon>
              <ListItemText primary={`${c.number} · ${c.title}`} secondary={`${c.customer} · ${c.status}`} />
            </ListItemButton>
          ))}
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
