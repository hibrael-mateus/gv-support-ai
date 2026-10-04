import { useEffect, useState, type ReactNode } from "react";
import {
  Alert, Box, Button, Card, CardActionArea, CardContent, Checkbox, FormControlLabel, FormGroup, IconButton, Stack, Switch,
  TextField, Typography,
} from "@mui/material";
import ArrowBackIcon from "@mui/icons-material/ArrowBack";
import StorageIcon from "@mui/icons-material/Storage";
import TerminalIcon from "@mui/icons-material/Terminal";
import ReceiptLongIcon from "@mui/icons-material/ReceiptLong";
import TravelExploreIcon from "@mui/icons-material/TravelExplore";
import CompareArrowsIcon from "@mui/icons-material/CompareArrows";
import ContentCopyOutlinedIcon from "@mui/icons-material/ContentCopyOutlined";
import ComputerIcon from "@mui/icons-material/Computer";
import { api, type Script, type Similar } from "../api";
import CodeBlock from "../components/CodeBlock";
import Markdown from "../components/Markdown";
import { DropZone, PageHeader } from "../components/common";
import { errorText, useNotify } from "../components/notify";
import type { Nav } from "../App";

const TOOLS: { id: string; title: string; text: string; icon: ReactNode }[] = [
  { id: "sql", title: "Gerador SQL", text: "Scripts de descoberta no catálogo e correção em transação, nunca com objetos inventados.", icon: <StorageIcon /> },
  { id: "ps", title: "Gerador PowerShell", text: "Um único script de diagnóstico que exporta TXT, CSV, JSON, LOG e ZIP.", icon: <TerminalIcon /> },
  { id: "log", title: "Analisador de logs", text: "Arraste um log: erro principal, consequentes, frequência e servidores.", icon: <ReceiptLongIcon /> },
  { id: "search", title: "Pesquisa de fontes", text: "Busca híbrida nas fontes GV Dasa autorizadas, com trecho e página.", icon: <TravelExploreIcon /> },
  { id: "compare", title: "Comparador de arquivos", text: "Diferenças entre dois arquivos de configuração, scripts ou logs.", icon: <CompareArrowsIcon /> },
  { id: "similar", title: "Caso semelhante", text: "Procura chamados e KIs parecidos com causa e solução anteriores.", icon: <ContentCopyOutlinedIcon /> },
  { id: "windows", title: "Diagnóstico Windows", text: "Script completo de sistema, disco, serviços, IIS, rede, eventos e certificados.", icon: <ComputerIcon /> },
];

export default function Tools({ go }: { go: Nav }) {
  const [tool, setTool] = useState("");
  const current = TOOLS.find((t) => t.id === tool);
  if (!current) {
    return (
      <Box>
        <PageHeader title="Ferramentas" subtitle="Utilitários do analista. Nenhum script é executado automaticamente." />
        <Box sx={{ display: "grid", gap: 2, gridTemplateColumns: "repeat(auto-fill, minmax(260px, 1fr))" }}>
          {TOOLS.map((t) => (
            <Card key={t.id}>
              <CardActionArea onClick={() => (t.id === "search" ? go({ page: "sources" }) : setTool(t.id))} sx={{ height: "100%" }}>
                <CardContent>
                  <Box sx={{ color: "primary.main", mb: 1 }}>{t.icon}</Box>
                  <Typography variant="subtitle1">{t.title}</Typography>
                  <Typography variant="body2" color="text.secondary">{t.text}</Typography>
                </CardContent>
              </CardActionArea>
            </Card>
          ))}
        </Box>
      </Box>
    );
  }
  return (
    <Box>
      <Stack direction="row" spacing={1} sx={{ alignItems: "center", mb: 2 }}>
        <IconButton aria-label="Voltar às ferramentas" onClick={() => setTool("")}><ArrowBackIcon /></IconButton>
        <Box>
          <Typography variant="h5" component="h1">{current.title}</Typography>
          <Typography variant="body2" color="text.secondary">{current.text}</Typography>
        </Box>
      </Stack>
      {tool === "sql" && <SqlTool />}
      {(tool === "ps" || tool === "windows") && <PowerShellTool all={tool === "windows"} />}
      {tool === "log" && <LogTool />}
      {tool === "compare" && <CompareTool />}
      {tool === "similar" && <SimilarTool />}
    </Box>
  );
}

function SqlTool() {
  const notify = useNotify();
  const [term, setTerm] = useState("");
  const [corr, setCorr] = useState({ table: "", where: "", set_clause: "", delete: false });
  const [check, setCheck] = useState("");
  const [scripts, setScripts] = useState<Script[]>([]);
  const wrap = async (fn: () => Promise<Script | Script[]>) => {
    try { const r = await fn(); setScripts(Array.isArray(r) ? r : [r]); } catch (e) { notify(errorText(e), "error"); }
  };
  return (
    <Stack spacing={2}>
      <Card><CardContent>
        <Typography variant="subtitle1">1. Descobrir objetos</Typography>
        <Typography variant="body2" color="text.secondary" sx={{ mb: 1.5 }}>Procura tabelas, colunas, procedures e views no catálogo do banco (INFORMATION_SCHEMA / sys.*).</Typography>
        <Stack direction="row" spacing={1}>
          <TextField label="Termo" placeholder="Ex.: matricula, boleto, parametro" value={term} onChange={(e) => setTerm(e.target.value)} />
          <Button variant="contained" disabled={!term.trim()} onClick={() => wrap(() => api.sqlDiscovery(term.trim()))} sx={{ flexShrink: 0 }}>Gerar descoberta</Button>
        </Stack>
      </CardContent></Card>
      <Card><CardContent>
        <Typography variant="subtitle1">2. Correção segura</Typography>
        <Typography variant="body2" color="text.secondary" sx={{ mb: 1.5 }}>Use apenas objetos confirmados na descoberta. Gera SELECT, análise, alteração em transação (COMMIT/ROLLBACK comentados) e validação.</Typography>
        <Box sx={{ display: "grid", gap: 1.5, gridTemplateColumns: { xs: "1fr", md: "1fr 1fr" } }}>
          <TextField label="Tabela confirmada" value={corr.table} onChange={(e) => setCorr({ ...corr, table: e.target.value })} />
          <TextField label="Filtro (WHERE)" value={corr.where} onChange={(e) => setCorr({ ...corr, where: e.target.value })} />
          <TextField label="Alteração (SET)" disabled={corr.delete} value={corr.set_clause} onChange={(e) => setCorr({ ...corr, set_clause: e.target.value })} />
          <FormControlLabel control={<Switch checked={corr.delete} onChange={(e) => setCorr({ ...corr, delete: e.target.checked })} />} label="É uma exclusão (DELETE)" />
        </Box>
        <Button sx={{ mt: 1.5 }} variant="outlined" disabled={!corr.table.trim() || !corr.where.trim()} onClick={() => wrap(() => api.sqlCorrection(corr))}>Gerar script de correção</Button>
      </CardContent></Card>
      <Card><CardContent>
        <Typography variant="subtitle1">Verificar um SQL existente</Typography>
        <TextField multiline minRows={4} sx={{ mt: 1, fontFamily: "monospace" }} placeholder="Cole um script para classificar o risco" value={check} onChange={(e) => setCheck(e.target.value)} />
        <Button sx={{ mt: 1.5 }} variant="outlined" disabled={!check.trim()} onClick={() => wrap(() => api.sqlCheck(check))}>Verificar</Button>
      </CardContent></Card>
      {scripts.map((s, i) => <CodeBlock key={i} code={s.code} language={s.language} title={s.title} reasons={s.reasons} warnings={s.warnings} />)}
    </Stack>
  );
}

function PowerShellTool({ all }: { all: boolean }) {
  const notify = useNotify();
  const [modules, setModules] = useState<{ id: string; label: string }[]>([]);
  const [picked, setPicked] = useState<string[]>([]);
  const [form, setForm] = useState({ target: "", sql_instance: "", urls: "", log_path: "", hours: 24 });
  const [script, setScript] = useState<Script | null>(null);
  const [canRun, setCanRun] = useState(false);
  const [output, setOutput] = useState("");

  useEffect(() => {
    api.psModules().then((m) => { setModules(m); setPicked(all ? m.map((x) => x.id) : ["sistema", "disco", "servicos", "rede", "eventos"]); });
    api.settings().then((s) => setCanRun(!!s.allow_local_execution)).catch(() => {});
  }, [all]);

  const generate = async () => {
    try {
      setScript(await api.powershell({ ...form, modules: picked, urls: form.urls.split(/[\s,;]+/).filter(Boolean), hours: Number(form.hours) || 24 }));
      setOutput("");
    } catch (e) { notify(errorText(e), "error"); }
  };
  const run = async () => {
    if (!script || !window.confirm("Executar este script de diagnóstico neste computador?")) return;
    try {
      const r = await api.execute(script.code);
      setOutput(`Código de saída: ${r.exit_code}\n\n${r.stdout}${r.stderr ? `\n[stderr]\n${r.stderr}` : ""}`);
    } catch (e) { notify(errorText(e), "error"); }
  };

  return (
    <Stack spacing={2}>
      <Card><CardContent>
        <Typography variant="subtitle1" sx={{ mb: 1 }}>Verificações</Typography>
        <FormGroup row>
          {modules.map((m) => (
            <FormControlLabel key={m.id} sx={{ width: 220 }} label={m.label} control={
              <Checkbox checked={picked.includes(m.id)} onChange={(e) => setPicked((p) => (e.target.checked ? [...p, m.id] : p.filter((x) => x !== m.id)))} />
            } />
          ))}
        </FormGroup>
        <Box sx={{ display: "grid", gap: 1.5, mt: 1.5, gridTemplateColumns: { xs: "1fr", md: "repeat(3, 1fr)" } }}>
          <TextField label="Servidor alvo (rede)" placeholder="PV990" value={form.target} onChange={(e) => setForm({ ...form, target: e.target.value })} />
          <TextField label="Instância SQL" placeholder="PV990\\SQL2019" value={form.sql_instance} onChange={(e) => setForm({ ...form, sql_instance: e.target.value })} />
          <TextField label="Horas de eventos" type="number" value={form.hours} onChange={(e) => setForm({ ...form, hours: Number(e.target.value) })} />
          <TextField label="URLs para testar" placeholder="https://portal.cliente.edu.br" value={form.urls} onChange={(e) => setForm({ ...form, urls: e.target.value })} sx={{ gridColumn: { md: "1 / 3" } }} />
          <TextField label="Pasta de logs" placeholder="C:\\inetpub\\logs\\LogFiles" value={form.log_path} onChange={(e) => setForm({ ...form, log_path: e.target.value })} />
        </Box>
        <Stack direction="row" spacing={1} sx={{ mt: 2 }}>
          <Button variant="contained" disabled={!picked.length} onClick={generate}>Gerar script</Button>
          {script && canRun && !script.dangerous && <Button variant="outlined" onClick={run}>Executar localmente</Button>}
        </Stack>
      </CardContent></Card>
      {script && <CodeBlock code={script.code} language="powershell" title={script.title} reasons={script.reasons} warnings={script.warnings} />}
      {output && <Box component="pre" sx={{ p: 2, bgcolor: "action.hover", borderRadius: 1, overflow: "auto", maxHeight: 400, fontSize: 13 }}>{output}</Box>}
    </Stack>
  );
}

function LogTool() {
  const notify = useNotify();
  const [text, setText] = useState("");
  const [md, setMd] = useState("");
  const [busy, setBusy] = useState(false);
  const analyze = async (input: File | string) => {
    setBusy(true);
    try { setMd((await api.analyzeLog(input)).markdown); } catch (e) { notify(errorText(e), "error"); } finally { setBusy(false); }
  };
  return (
    <DropZone onFiles={(f) => analyze(f[0])} label="Solte o log para analisar">
      <Card><CardContent>
        <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>Arraste um arquivo do Explorer para esta área, selecione um arquivo ou cole o conteúdo.</Typography>
        <TextField multiline minRows={6} maxRows={16} value={text} onChange={(e) => setText(e.target.value)} placeholder="Cole o log aqui" />
        <Stack direction="row" spacing={1} sx={{ mt: 1.5 }}>
          <Button variant="contained" loading={busy} disabled={!text.trim()} onClick={() => analyze(text)}>Analisar</Button>
          <Button variant="outlined" component="label">Selecionar arquivo<input hidden type="file" onChange={(e) => e.target.files?.[0] && analyze(e.target.files[0])} /></Button>
        </Stack>
      </CardContent></Card>
      {md && <Card sx={{ mt: 2 }}><CardContent><Markdown>{md}</Markdown></CardContent></Card>}
    </DropZone>
  );
}

function CompareTool() {
  const notify = useNotify();
  const [a, setA] = useState({ name: "arquivo A", text: "" });
  const [b, setB] = useState({ name: "arquivo B", text: "" });
  const [res, setRes] = useState<Awaited<ReturnType<typeof api.compare>> | null>(null);
  const load = (set: typeof setA) => async (f: File) => set({ name: f.name, text: await f.text() });
  const side = (v: typeof a, set: typeof setA) => (
    <DropZone onFiles={(f) => load(set)(f[0])} label="Solte o arquivo">
      <Stack spacing={1}>
        <Stack direction="row" spacing={1} sx={{ alignItems: "center" }}>
          <Typography variant="subtitle1" sx={{ flex: 1 }} noWrap>{v.name}</Typography>
          <Button size="small" component="label">Abrir<input hidden type="file" onChange={(e) => e.target.files?.[0] && load(set)(e.target.files[0])} /></Button>
        </Stack>
        <TextField multiline minRows={10} maxRows={20} value={v.text} onChange={(e) => set({ ...v, text: e.target.value })} slotProps={{ htmlInput: { style: { fontFamily: "Consolas, monospace", fontSize: 13 } } }} />
      </Stack>
    </DropZone>
  );
  return (
    <Stack spacing={2}>
      <Box sx={{ display: "grid", gap: 2, gridTemplateColumns: { xs: "1fr", md: "1fr 1fr" } }}>{side(a, setA)}{side(b, setB)}</Box>
      <Button variant="contained" sx={{ alignSelf: "flex-start" }} onClick={async () => {
        try { setRes(await api.compare(a.text, b.text, a.name, b.name)); } catch (e) { notify(errorText(e), "error"); }
      }}>Comparar</Button>
      {res && (
        <Card><CardContent>
          <Typography sx={{ mb: 1 }}>Similaridade {res.similarity}% · {res.added} linha(s) adicionada(s) · {res.removed} removida(s)</Typography>
          {res.diff ? <CodeBlock code={res.diff} language="diff" title="Diferenças" /> : <Alert severity="success">Os arquivos são idênticos.</Alert>}
        </CardContent></Card>
      )}
    </Stack>
  );
}

function SimilarTool() {
  const notify = useNotify();
  const [text, setText] = useState("");
  const [res, setRes] = useState<{ content: string; meta: { similar?: Similar[] } } | null>(null);
  const [busy, setBusy] = useState(false);
  return (
    <Stack spacing={2}>
      <Card><CardContent>
        <TextField multiline minRows={3} label="Descreva o problema ou cole a mensagem de erro" value={text} onChange={(e) => setText(e.target.value)} />
        <Button sx={{ mt: 1.5 }} variant="contained" loading={busy} disabled={!text.trim()} onClick={async () => {
          setBusy(true);
          try { setRes(await api.similar(text)); } catch (e) { notify(errorText(e), "error"); } finally { setBusy(false); }
        }}>Buscar casos semelhantes</Button>
      </CardContent></Card>
      {res && <Card><CardContent><Markdown>{res.content}</Markdown></CardContent></Card>}
    </Stack>
  );
}
