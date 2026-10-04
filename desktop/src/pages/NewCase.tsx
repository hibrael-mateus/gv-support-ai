import { useState } from "react";
import { Box, Button, Card, CardContent, Chip, MenuItem, Stack, TextField, Typography } from "@mui/material";
import PlayArrowIcon from "@mui/icons-material/PlayArrow";
import AttachFileIcon from "@mui/icons-material/AttachFile";
import { api } from "../api";
import { DropZone, PageHeader } from "../components/common";
import { errorText, useNotify } from "../components/notify";
import type { Nav } from "../App";

const PRODUCTS = ["GVcollege", "GVcollege PRO", "GVmobile", "GVcentris", "GVerp", "GVsign", "Portal do Professor", "Portal do Aluno", "Pergamum", "EDUmessenger", "Outro"];
const ENVIRONMENTS = ["Produção", "Homologação", "SaaS (nuvem GV)", "On-premise (cliente)", "Desenvolvimento"];

const FIELDS: { key: string; label: string; multiline?: boolean; select?: string[]; span?: boolean; placeholder?: string }[] = [
  { key: "customer", label: "Cliente" },
  { key: "product", label: "Produto", select: PRODUCTS },
  { key: "module", label: "Módulo" },
  { key: "routine", label: "Rotina" },
  { key: "menu", label: "Menu" },
  { key: "screen", label: "Tela" },
  { key: "environment", label: "Ambiente", select: ENVIRONMENTS },
  { key: "server", label: "Servidor", placeholder: "Ex.: PV990" },
  { key: "database_name", label: "Banco de dados" },
  { key: "error_message", label: "Mensagem de erro", multiline: true, span: true },
  { key: "description", label: "Descrição", multiline: true, span: true },
  { key: "already_validated", label: "O que já foi validado", multiline: true, span: true, placeholder: "Um teste por linha. Ex.:\nPV990 acessível = OK\nDNS PV990 = OK" },
];

export default function NewCase({ go }: { go: Nav }) {
  const notify = useNotify();
  const [form, setForm] = useState<Record<string, string>>({ title: "" });
  const [files, setFiles] = useState<File[]>([]);
  const [busy, setBusy] = useState(false);
  const set = (k: string, v: string) => setForm((f) => ({ ...f, [k]: v }));

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!form.title?.trim() && !form.error_message?.trim() && !form.description?.trim()) {
      notify("Informe ao menos o título, a mensagem de erro ou a descrição.", "warning");
      return;
    }
    setBusy(true);
    try {
      const created = await api.createCase(form);
      for (const f of files) await api.uploadAttachment(created.id, f);
      go({ page: "case", id: created.id, autoInvestigate: true });
    } catch (err) {
      notify(errorText(err), "error");
      setBusy(false);
    }
  };

  return (
    <DropZone onFiles={(f) => setFiles((old) => [...old, ...f])} label="Solte para anexar ao chamado">
      <Box component="form" onSubmit={submit}>
        <PageHeader title="Novo chamado" subtitle="Registre o cenário; o agente conduz a investigação a partir daqui." />
        <Card>
          <CardContent>
            <Stack spacing={2}>
              <TextField label="Título / resumo do problema" autoFocus slotProps={{ inputLabel: { shrink: true } }} value={form.title} onChange={(e) => set("title", e.target.value)}
                placeholder="Ex.: Portal Professor apresenta erro ao gerar o diário" />
              <Box sx={{ display: "grid", gap: 2, gridTemplateColumns: { xs: "1fr", md: "repeat(3, minmax(0, 1fr))" } }}>
                {FIELDS.map((f) => (
                  <TextField
                    key={f.key}
                    label={f.label}
                    value={form[f.key] ?? ""}
                    onChange={(e) => set(f.key, e.target.value)}
                    select={!!f.select}
                    multiline={f.multiline}
                    minRows={f.multiline ? 3 : undefined}
                    placeholder={f.placeholder}
                    sx={f.span ? { gridColumn: "1 / -1" } : undefined}
                  >
                    {f.select?.map((o) => <MenuItem key={o} value={o}>{o}</MenuItem>)}
                  </TextField>
                ))}
              </Box>
              <Box>
                <Typography variant="body2" sx={{ fontWeight: 600, mb: 1 }}>Anexos</Typography>
                <Stack direction="row" spacing={1} sx={{ flexWrap: "wrap", rowGap: 1, alignItems: "center" }}>
                  {files.map((f, i) => <Chip key={i} label={f.name} onDelete={() => setFiles((old) => old.filter((_, j) => j !== i))} />)}
                  <Button component="label" variant="outlined" startIcon={<AttachFileIcon />}>
                    Adicionar
                    <input hidden type="file" multiple onChange={(e) => setFiles((old) => [...old, ...Array.from(e.target.files ?? [])])} />
                  </Button>
                  <Typography variant="caption" color="text.secondary">ou arraste arquivos do Explorer (logs, prints, PDF, DOCX, XLSX, ZIP)</Typography>
                </Stack>
              </Box>
            </Stack>
          </CardContent>
        </Card>
        <Stack direction="row" spacing={1} sx={{ justifyContent: "flex-end", mt: 2 }}>
          <Button onClick={() => go({ page: "dashboard" })}>Cancelar</Button>
          <Button type="submit" variant="contained" size="large" startIcon={<PlayArrowIcon />} loading={busy}>
            Iniciar investigação
          </Button>
        </Stack>
      </Box>
    </DropZone>
  );
}
