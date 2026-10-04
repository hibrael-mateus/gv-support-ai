import { useEffect, useState } from "react";
import {
  Box, Button, IconButton, InputAdornment, MenuItem, Paper, Table, TableBody, TableCell, TableContainer, TableHead, TableRow,
  TextField, Tooltip, Typography,
} from "@mui/material";
import SearchIcon from "@mui/icons-material/Search";
import AddIcon from "@mui/icons-material/Add";
import DeleteOutlineIcon from "@mui/icons-material/DeleteOutlined";
import { api, type Case } from "../api";
import { CaseStatusChip, PageHeader, formatDate } from "../components/common";
import { errorText, useNotify } from "../components/notify";
import type { Nav } from "../App";

const STATUSES = ["Em investigação", "Aguardando cliente", "Solucionado", "Escalonado N3", "Cancelado"];
const CLOSED = new Set(["Solucionado", "Escalonado N3", "Cancelado"]);

/** Case list. With `history`, shows closed cases with their root cause and resolution. */
export default function Cases({ go, history = false }: { go: Nav; history?: boolean }) {
  const notify = useNotify();
  const [rows, setRows] = useState<Case[]>([]);
  const [status, setStatus] = useState("");
  const [query, setQuery] = useState("");

  const load = () => api.cases(status, query).then((r) => setRows(history ? r.filter((c) => CLOSED.has(c.status)) : r)).catch((e) => notify(errorText(e), "error"));
  useEffect(() => {
    const t = setTimeout(load, 250);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [status, query, history]);

  const remove = async (c: Case) => {
    if (!window.confirm(`Excluir o chamado ${c.number}? Mensagens, hipóteses e anexos serão removidos.`)) return;
    try { await api.deleteCase(c.id); load(); } catch (e) { notify(errorText(e), "error"); }
  };

  return (
    <Box>
      <PageHeader
        title={history ? "Histórico" : "Chamados"}
        subtitle={history ? "Chamados encerrados, com causa raiz e solução aplicada." : "Todos os chamados investigados neste computador."}
        actions={!history && <Button variant="contained" startIcon={<AddIcon />} onClick={() => go({ page: "new" })}>Novo chamado</Button>}
      />
      <Box sx={{ display: "flex", gap: 1.5, mb: 2, flexWrap: "wrap" }}>
        <TextField sx={{ maxWidth: 420 }} placeholder="Buscar por cliente, título, erro, produto…" value={query} onChange={(e) => setQuery(e.target.value)}
          slotProps={{ input: { startAdornment: <InputAdornment position="start"><SearchIcon /></InputAdornment> } }} />
        <TextField select label="Status" sx={{ maxWidth: 220 }} value={status} onChange={(e) => setStatus(e.target.value)}>
          <MenuItem value="">Todos</MenuItem>
          {STATUSES.filter((s) => !history || CLOSED.has(s)).map((s) => <MenuItem key={s} value={s}>{s}</MenuItem>)}
        </TextField>
      </Box>
      <TableContainer component={Paper} variant="outlined">
        <Table size="small">
          <TableHead>
            <TableRow>
              <TableCell>Número</TableCell>
              <TableCell>Título</TableCell>
              <TableCell>Cliente</TableCell>
              <TableCell>Produto</TableCell>
              {history ? <TableCell>Causa raiz</TableCell> : <TableCell>Status</TableCell>}
              <TableCell>Atualizado</TableCell>
              <TableCell />
            </TableRow>
          </TableHead>
          <TableBody>
            {rows.map((c) => (
              <TableRow key={c.id} hover sx={{ cursor: "pointer" }} onClick={() => go({ page: "case", id: c.id })}>
                <TableCell sx={{ whiteSpace: "nowrap" }}>{c.number}</TableCell>
                <TableCell sx={{ maxWidth: 360 }}><Typography variant="body2" noWrap title={c.title}>{c.title || "-"}</Typography></TableCell>
                <TableCell>{c.customer || "-"}</TableCell>
                <TableCell>{c.product || "-"}</TableCell>
                {history
                  ? <TableCell sx={{ maxWidth: 320 }}><Typography variant="body2" noWrap title={c.root_cause}>{c.root_cause || <CaseStatusChip status={c.status} />}</Typography></TableCell>
                  : <TableCell><CaseStatusChip status={c.status} /></TableCell>}
                <TableCell sx={{ whiteSpace: "nowrap" }}>{formatDate(c.updated_at)}</TableCell>
                <TableCell align="right" onClick={(e) => e.stopPropagation()}>
                  <Tooltip title="Excluir chamado"><IconButton size="small" aria-label="Excluir chamado" onClick={() => remove(c)}><DeleteOutlineIcon fontSize="small" /></IconButton></Tooltip>
                </TableCell>
              </TableRow>
            ))}
            {!rows.length && (
              <TableRow><TableCell colSpan={7}><Typography variant="body2" color="text.secondary" sx={{ py: 2, textAlign: "center" }}>Nenhum chamado encontrado.</Typography></TableCell></TableRow>
            )}
          </TableBody>
        </Table>
      </TableContainer>
    </Box>
  );
}
