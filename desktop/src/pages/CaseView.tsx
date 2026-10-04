import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Alert, Box, Button, Card, CardContent, Chip, Dialog, DialogActions, DialogContent, DialogTitle, Divider, IconButton,
  List, ListItem, ListItemText, Menu, MenuItem, Paper, Stack, Tab, Tabs, TextField, Tooltip, Typography,
} from "@mui/material";
import DeleteOutlineIcon from "@mui/icons-material/DeleteOutlined";
import AddIcon from "@mui/icons-material/Add";
import ArrowBackIcon from "@mui/icons-material/ArrowBack";
import EditOutlinedIcon from "@mui/icons-material/EditOutlined";
import { api, type Case, type Hypothesis, type Message, type Source } from "../api";
import ChatPanel from "../components/ChatPanel";
import CodeBlock from "../components/CodeBlock";
import { SourceList } from "../components/Sources";
import Markdown from "../components/Markdown";
import { CaseStatusChip, HypothesisChip, formatDate } from "../components/common";
import { errorText, useNotify } from "../components/notify";
import type { Nav } from "../App";

const STATUSES = ["Em investigação", "Aguardando cliente", "Solucionado", "Escalonado N3", "Cancelado"];
const HYP_STATUSES = ["Não validada", "Em análise", "Muito provável", "Confirmada", "Descartada"];
const NEEDS_EVIDENCE = new Set(["Confirmada", "Descartada"]);
const TABS = ["Diagnóstico", "Evidências", "Hipóteses", "Testes", "Scripts", "Fontes", "Histórico"];

export default function CaseView({ id, autoInvestigate, go }: { id: number; autoInvestigate?: boolean; go: Nav }) {
  const notify = useNotify();
  const [c, setCase] = useState<Case | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [busy, setBusy] = useState(false);
  const [tab, setTab] = useState(0);
  const [statusMenu, setStatusMenu] = useState<HTMLElement | null>(null);
  const [pending, setPending] = useState<{ h: Hypothesis; status: string } | null>(null);
  const started = useRef(false);

  const load = useCallback(async () => {
    const [cc, mm] = await Promise.all([api.getCase(id), api.caseMessages(id)]);
    setCase(cc);
    setMessages(mm);
    return mm;
  }, [id]);

  const run = useCallback(async (message: string, action = "investigar") => {
    setBusy(true);
    if (message) setMessages((m) => [...m, { id: -Date.now(), case_id: id, role: "user", content: message, agent: "", sources: [], meta: {}, created_at: new Date().toISOString().replace("Z", "") }]);
    try {
      const r = await api.investigate(id, message, action);
      setCase(r.case);
      setMessages(await api.caseMessages(id));
    } catch (e) {
      notify(errorText(e), "error");
    } finally {
      setBusy(false);
    }
  }, [id, notify]);

  useEffect(() => {
    started.current = false;
    load().then((mm) => {
      if (autoInvestigate && !started.current && mm.length === 0) {
        started.current = true;
        run("", "investigar");
      }
    }).catch((e) => notify(errorText(e), "error"));
  }, [load, autoInvestigate, run, notify]);

  const upload = async (files: File[], text: string) => {
    try {
      for (const f of files) await api.uploadAttachment(id, f);
      notify(`${files.length} arquivo(s) anexado(s)`);
      const isLog = files.some((f) => /\.(log|txt|csv|evtx|json)$/i.test(f.name));
      await run(text, isLog ? "analisar_log" : "investigar");
    } catch (e) {
      notify(errorText(e), "error");
    }
  };

  const setStatus = async (status: string) => {
    setStatusMenu(null);
    try { setCase(await api.patchCase(id, { status })); } catch (e) { notify(errorText(e), "error"); }
  };

  const changeHypothesis = async (h: Hypothesis, status: string, evidence?: string) => {
    if (NEEDS_EVIDENCE.has(status) && !evidence) { setPending({ h, status }); return; }
    try {
      await api.patchHypothesis(h.id, { status, ...(evidence ? { evidence } : {}) });
      await load();
    } catch (e) {
      notify(errorText(e), "error");
    }
  };

  const scripts = useMemo(() => messages.flatMap((m) => (m.meta?.scripts ?? []).map((s) => ({ ...s, at: m.created_at }))), [messages]);
  const sources = useMemo(() => {
    const seen = new Map<string, Source>();
    for (const m of messages) for (const s of m.sources ?? []) {
      const k = `${s.drive_file_id}:${s.page}`;
      if (!seen.has(k) || seen.get(k)!.relevance < s.relevance) seen.set(k, s);
    }
    return [...seen.values()].sort((a, b) => b.relevance - a.relevance);
  }, [messages]);

  if (!c) return <Typography color="text.secondary">Carregando chamado…</Typography>;
  const details = [
    ["Cliente", c.customer], ["Produto", c.product], ["Módulo", c.module], ["Rotina", c.routine], ["Menu", c.menu],
    ["Tela", c.screen], ["Ambiente", c.environment], ["Servidor", c.server], ["Banco", c.database_name],
  ].filter(([, v]) => v);

  return (
    <Box sx={{ display: "flex", flexDirection: "column", height: "100%", minHeight: 0 }}>
      <Stack direction="row" spacing={1} sx={{ alignItems: "center", mb: 1.5, flexWrap: "wrap", rowGap: 1 }}>
        <Tooltip title="Voltar aos chamados"><IconButton aria-label="Voltar" onClick={() => go({ page: "cases" })}><ArrowBackIcon /></IconButton></Tooltip>
        <Box sx={{ flex: 1, minWidth: 260 }}>
          <Typography variant="h6" component="h1" noWrap title={c.title}>{c.number} · {c.title || "Chamado sem título"}</Typography>
          <Typography variant="body2" color="text.secondary" noWrap>{details.map(([k, v]) => `${k}: ${v}`).join(" · ") || "Sem detalhes do ambiente"}</Typography>
        </Box>
        <CaseStatusChip status={c.status} />
        <Button size="small" variant="outlined" startIcon={<EditOutlinedIcon />} onClick={(e) => setStatusMenu(e.currentTarget)}>Alterar status</Button>
        <Menu anchorEl={statusMenu} open={!!statusMenu} onClose={() => setStatusMenu(null)}>
          {STATUSES.map((s) => <MenuItem key={s} selected={s === c.status} onClick={() => setStatus(s)}>{s}</MenuItem>)}
        </Menu>
      </Stack>

      <Box sx={{ flex: 1, minHeight: 0, display: "grid", gap: 2, gridTemplateColumns: { xs: "1fr", lg: "minmax(0, 1fr) 320px" } }}>
        <Paper variant="outlined" sx={{ display: "flex", flexDirection: "column", minHeight: 0, overflow: "hidden" }}>
          <Tabs value={tab} onChange={(_, v) => setTab(v)} variant="scrollable" sx={{ borderBottom: 1, borderColor: "divider", px: 1 }}>
            {TABS.map((t, i) => <Tab key={t} label={t + (i === 4 && scripts.length ? ` (${scripts.length})` : i === 5 && sources.length ? ` (${sources.length})` : "")} />)}
          </Tabs>
          <Box sx={{ flex: 1, minHeight: 0, display: "flex", flexDirection: "column" }}>
            {tab === 0 && (
              <ChatPanel
                messages={messages}
                busy={busy}
                onSend={(t) => run(t)}
                onAction={(a, t) => run(t, a)}
                onFiles={upload}
                placeholder="Informe o resultado de um teste, cole um erro ou peça um próximo passo… (Ctrl+Enter)"
                toolbar={c.root_cause ? <Alert severity="success" sx={{ mb: 1 }}><strong>Causa raiz confirmada:</strong> {c.root_cause}</Alert> : null}
                empty={<EmptyCase c={c} onStart={() => run("", "investigar")} />}
              />
            )}
            {tab === 1 && <Box sx={{ p: 2, overflowY: "auto" }}><Evidence c={c} reload={load} /></Box>}
            {tab === 2 && (
              <Box sx={{ p: 2, overflowY: "auto" }}>
                <HypothesisList c={c} onChange={changeHypothesis} reload={load} full />
              </Box>
            )}
            {tab === 3 && (
              <Box sx={{ p: 2, overflowY: "auto" }}>
                {c.hypotheses.filter((h) => h.test).length === 0 && <Typography color="text.secondary">Nenhum teste sugerido ainda. Use “Investigar”.</Typography>}
                {c.hypotheses.filter((h) => h.test).map((h) => (
                  <Card key={h.id} sx={{ mb: 1.5 }}>
                    <CardContent>
                      <Stack direction="row" spacing={1} sx={{ alignItems: "center", mb: 1 }}>
                        <Typography sx={{ fontWeight: 600, flex: 1 }}>{h.title}</Typography>
                        <HypothesisChip status={h.status} />
                      </Stack>
                      <Markdown>{h.test}</Markdown>
                    </CardContent>
                  </Card>
                ))}
              </Box>
            )}
            {tab === 4 && (
              <Box sx={{ p: 2, overflowY: "auto" }}>
                {!scripts.length && <Typography color="text.secondary">Nenhum script gerado neste chamado. Use “Gerar SQL” ou “Gerar PowerShell”.</Typography>}
                {scripts.map((s, i) => <CodeBlock key={i} code={s.code} language={s.language} title={`${s.title} · ${formatDate(s.at)}`} reasons={s.reasons} warnings={s.warnings} />)}
              </Box>
            )}
            {tab === 5 && (
              <Box sx={{ p: 1, overflowY: "auto" }}>
                {!sources.length && <Typography color="text.secondary" sx={{ p: 1 }}>Nenhuma fonte consultada ainda.</Typography>}
                <SourceList sources={sources} />
              </Box>
            )}
            {tab === 6 && (
              <Box sx={{ p: 2, overflowY: "auto" }}>
                <List dense>
                  <ListItem><ListItemText primary="Chamado aberto" secondary={formatDate(c.created_at)} /></ListItem>
                  {messages.map((m) => (
                    <ListItem key={m.id} divider>
                      <ListItemText
                        primary={m.role === "user" ? "Analista" : m.agent || "Assistente"}
                        secondary={`${formatDate(m.created_at)} · ${m.content.replace(/[#*`>|]/g, "").slice(0, 180)}`}
                      />
                    </ListItem>
                  ))}
                  <ListItem><ListItemText primary="Última atualização" secondary={formatDate(c.updated_at)} /></ListItem>
                </List>
              </Box>
            )}
          </Box>
        </Paper>

        <Stack spacing={2} sx={{ minHeight: 0, overflowY: "auto", display: { xs: "none", lg: "flex" } }}>
          <Card>
            <CardContent>
              <Typography variant="subtitle1" sx={{ mb: 1 }}>Hipóteses</Typography>
              <HypothesisList c={c} onChange={changeHypothesis} reload={load} />
            </CardContent>
          </Card>
          <Card>
            <CardContent>
              <Typography variant="subtitle1">Memória do chamado</Typography>
              <Typography variant="caption" color="text.secondary">O agente não pergunta novamente o que já foi validado.</Typography>
              <Stack spacing={0.5} sx={{ mt: 1 }}>
                {c.facts.map((f) => (
                  <Stack key={f.id} direction="row" spacing={1} sx={{ alignItems: "center" }}>
                    <Chip size="small" label={f.status} color={f.status === "OK" ? "success" : f.status === "FALHA" ? "error" : "default"} sx={{ minWidth: 58 }} />
                    <Typography variant="body2" sx={{ overflowWrap: "anywhere" }}>{f.key} = {f.value}</Typography>
                  </Stack>
                ))}
                {!c.facts.length && <Typography variant="body2" color="text.secondary">Nada validado ainda.</Typography>}
              </Stack>
            </CardContent>
          </Card>
        </Stack>
      </Box>

      <EvidenceDialog pending={pending} onClose={() => setPending(null)} onSave={(ev) => { const p = pending!; setPending(null); changeHypothesis(p.h, p.status, ev); }} />
    </Box>
  );
}

function EmptyCase({ c, onStart }: { c: Case; onStart: () => void }) {
  return (
    <Stack spacing={1.5} sx={{ alignItems: "flex-start", maxWidth: 640 }}>
      {c.error_message && <Alert severity="error" sx={{ width: "100%", whiteSpace: "pre-wrap" }}>{c.error_message}</Alert>}
      {c.description && <Typography variant="body2" sx={{ whiteSpace: "pre-wrap" }}>{c.description}</Typography>}
      <Button variant="contained" onClick={onStart}>Iniciar investigação</Button>
    </Stack>
  );
}

function HypothesisList({ c, onChange, reload, full = false }: { c: Case; onChange: (h: Hypothesis, s: string) => void; reload: () => Promise<unknown>; full?: boolean }) {
  const notify = useNotify();
  const [title, setTitle] = useState("");
  const add = async () => {
    if (!title.trim()) return;
    try { await api.addHypothesis(c.id, title.trim()); setTitle(""); await reload(); } catch (e) { notify(errorText(e), "error"); }
  };
  return (
    <Stack spacing={1.25}>
      {c.hypotheses.map((h) => (
        <Box key={h.id} sx={{ border: 1, borderColor: "divider", borderRadius: 1, p: 1.25 }}>
          <Typography variant="body2" sx={{ fontWeight: 600, mb: 0.75 }}>{h.title}</Typography>
          {full && h.rationale && <Typography variant="body2" color="text.secondary" sx={{ mb: 0.75 }}>{h.rationale}</Typography>}
          <TextField select value={h.status} onChange={(e) => onChange(h, e.target.value)} slotProps={{ htmlInput: { "aria-label": `Status da hipótese ${h.title}` } }}>
            {HYP_STATUSES.map((s) => <MenuItem key={s} value={s}><HypothesisChip status={s} /></MenuItem>)}
          </TextField>
          {h.evidence && <Typography variant="caption" color="text.secondary" sx={{ display: "block", mt: 0.75 }}>Evidência: {h.evidence}</Typography>}
        </Box>
      ))}
      {!c.hypotheses.length && <Typography variant="body2" color="text.secondary">Nenhuma hipótese registrada.</Typography>}
      <Stack direction="row" spacing={1}>
        <TextField placeholder="Nova hipótese" value={title} onChange={(e) => setTitle(e.target.value)} onKeyDown={(e) => e.key === "Enter" && add()} />
        <IconButton aria-label="Adicionar hipótese" onClick={add}><AddIcon /></IconButton>
      </Stack>
    </Stack>
  );
}

function EvidenceDialog({ pending, onClose, onSave }: { pending: { h: Hypothesis; status: string } | null; onClose: () => void; onSave: (evidence: string) => void }) {
  const [text, setText] = useState("");
  useEffect(() => setText(""), [pending]);
  return (
    <Dialog open={!!pending} onClose={onClose} maxWidth="sm" fullWidth>
      <DialogTitle>Marcar como “{pending?.status}”</DialogTitle>
      <DialogContent>
        <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
          Uma hipótese só pode ser confirmada ou descartada com evidência (resultado de teste, query, log ou print).
        </Typography>
        <TextField autoFocus multiline minRows={3} label="Evidência" value={text} onChange={(e) => setText(e.target.value)}
          placeholder="Ex.: SELECT em SYS_PARAMETRO retornou VALOR = 'N' no servidor PV990" />
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>Cancelar</Button>
        <Button variant="contained" disabled={text.trim().length < 5} onClick={() => onSave(text.trim())}>Salvar</Button>
      </DialogActions>
    </Dialog>
  );
}

function Evidence({ c, reload }: { c: Case; reload: () => Promise<unknown> }) {
  const notify = useNotify();
  const [key, setKey] = useState("");
  const [value, setValue] = useState("");
  const add = async () => {
    if (!key.trim() || !value.trim()) return;
    try { await api.addFact(c.id, key.trim(), value.trim()); setKey(""); setValue(""); await reload(); } catch (e) { notify(errorText(e), "error"); }
  };
  const remove = async (id: number) => {
    try { await api.deleteFact(id); await reload(); } catch (e) { notify(errorText(e), "error"); }
  };
  return (
    <Stack spacing={2}>
      <Box>
        <Typography variant="subtitle1" sx={{ mb: 1 }}>Testes já realizados</Typography>
        <List dense disablePadding>
          {c.facts.map((f) => (
            <ListItem key={f.id} divider secondaryAction={<IconButton aria-label="Remover" edge="end" onClick={() => remove(f.id)}><DeleteOutlineIcon /></IconButton>}>
              <Chip size="small" label={f.status} color={f.status === "OK" ? "success" : f.status === "FALHA" ? "error" : "default"} sx={{ mr: 1.5, minWidth: 58 }} />
              <ListItemText primary={`${f.key} = ${f.value}`} secondary={`${f.source || "analista"} · ${formatDate(f.created_at)}`} />
            </ListItem>
          ))}
        </List>
        <Stack direction="row" spacing={1} sx={{ mt: 1.5 }}>
          <TextField label="Teste" placeholder="DNS PV990" value={key} onChange={(e) => setKey(e.target.value)} />
          <TextField label="Resultado" placeholder="OK" value={value} onChange={(e) => setValue(e.target.value)} onKeyDown={(e) => e.key === "Enter" && add()} />
          <Button variant="outlined" onClick={add} sx={{ flexShrink: 0 }}>Registrar</Button>
        </Stack>
      </Box>
      <Divider />
      <Box>
        <Typography variant="subtitle1" sx={{ mb: 1 }}>Anexos</Typography>
        {!c.attachments.length && <Typography variant="body2" color="text.secondary">Arraste arquivos para a aba Diagnóstico para anexá-los.</Typography>}
        <List dense disablePadding>
          {c.attachments.map((a) => (
            <ListItem key={a.id} divider><ListItemText primary={a.name} secondary={`${(a.size / 1024).toFixed(1)} KB · ${formatDate(a.created_at)}`} /></ListItem>
          ))}
        </List>
      </Box>
      {(c.error_message || c.description || c.already_validated) && (
        <>
          <Divider />
          <Box>
            <Typography variant="subtitle1" sx={{ mb: 1 }}>Relato original</Typography>
            {c.error_message && <Alert severity="error" sx={{ mb: 1, whiteSpace: "pre-wrap" }}>{c.error_message}</Alert>}
            <Typography variant="body2" sx={{ whiteSpace: "pre-wrap" }}>{c.description}</Typography>
          </Box>
        </>
      )}
    </Stack>
  );
}
