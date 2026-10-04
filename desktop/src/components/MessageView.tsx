import { useState } from "react";
import {
  Accordion, AccordionDetails, AccordionSummary, Alert, Avatar, Box, Button, Chip, Dialog, DialogActions, DialogContent,
  DialogTitle, FormControlLabel, IconButton, Paper, Radio, RadioGroup, Stack, TextField, Tooltip, Typography,
} from "@mui/material";
import ThumbUpOutlinedIcon from "@mui/icons-material/ThumbUpOutlined";
import ThumbDownOutlinedIcon from "@mui/icons-material/ThumbDownOutlined";
import ExpandMoreIcon from "@mui/icons-material/ExpandMore";
import SmartToyOutlinedIcon from "@mui/icons-material/SmartToyOutlined";
import PersonOutlineIcon from "@mui/icons-material/PersonOutlined";
import ContentCopyIcon from "@mui/icons-material/ContentCopy";
import { api, type Message } from "../api";
import Markdown from "./Markdown";
import CodeBlock from "./CodeBlock";
import { SourceList } from "./Sources";
import { errorText, useNotify } from "./notify";
import { copyText } from "../native";

const REASONS = ["Informação incorreta", "Fonte incorreta", "SQL incorreto", "PowerShell incorreto", "Não encontrou documentação", "Resposta incompleta", "Outro"];

const AGENT_LABEL: Record<string, string> = {
  GVSupportOrchestrator: "Orquestrador", DocumentationAgent: "Documentation Agent", SQLAgent: "SQL Agent",
  PowerShellAgent: "PowerShell Agent", LogAnalysisAgent: "Log Analysis Agent", SimilarCaseAgent: "Similar Case Agent",
  ValidationAgent: "Validation Agent", CustomerResponseAgent: "Customer Response Agent", N3EscalationAgent: "N3 Escalation Agent",
};

export default function MessageView({ message }: { message: Message }) {
  const notify = useNotify();
  const [vote, setVote] = useState<null | boolean>(null);
  const [askReason, setAskReason] = useState(false);
  const [reason, setReason] = useState(REASONS[0]);
  const [comment, setComment] = useState("");
  const mine = message.role === "user";
  const scripts = message.meta?.scripts ?? [];
  const validation = message.meta?.validation ?? [];

  const send = async (useful: boolean, why = "", text = "") => {
    try {
      await api.feedback(message.id, useful, why, text);
      setVote(useful);
      notify("Obrigado pelo feedback");
    } catch (e) {
      notify(errorText(e), "error");
    }
  };

  return (
    <Stack direction="row" spacing={1.5} sx={{ alignItems: "flex-start", justifyContent: mine ? "flex-end" : "flex-start", mb: 2 }}>
      {!mine && (
        <Avatar sx={{ bgcolor: "primary.main", width: 32, height: 32 }}>
          <SmartToyOutlinedIcon fontSize="small" />
        </Avatar>
      )}
      <Paper
        variant="outlined"
        sx={{ p: 1.5, px: 2, maxWidth: mine ? "75%" : "min(100%, 980px)", minWidth: 0, flex: mine ? "0 1 auto" : 1,
              bgcolor: mine ? "action.selected" : "background.paper", borderColor: mine ? "primary.light" : "divider" }}
      >
        {!mine && message.agent && (
          <Chip size="small" variant="outlined" color="primary" label={AGENT_LABEL[message.agent] ?? message.agent} sx={{ mb: 1 }} />
        )}
        {mine ? <Typography variant="body2" sx={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>{message.content}</Typography> : <Markdown>{message.content}</Markdown>}
        {scripts.map((s, i) => (
          <CodeBlock key={i} code={s.code} language={s.language} title={s.title} reasons={s.reasons} warnings={s.warnings} />
        ))}
        {validation.length > 0 && (
          <Alert severity="info" sx={{ mt: 1 }}>
            <strong>Validação anti-alucinação:</strong> {validation.join(" • ")}
          </Alert>
        )}
        {message.sources?.length > 0 && (
          <Accordion disableGutters variant="outlined" sx={{ mt: 1.5 }}>
            <AccordionSummary expandIcon={<ExpandMoreIcon />}>
              <Typography variant="body2" sx={{ fontWeight: 600 }}>Fontes consultadas ({message.sources.length})</Typography>
            </AccordionSummary>
            <AccordionDetails sx={{ p: 0.5 }}>
              <SourceList sources={message.sources} />
            </AccordionDetails>
          </Accordion>
        )}
        {!mine && (
          <Stack direction="row" spacing={0.5} sx={{ mt: 1, alignItems: "center" }}>
            <Typography variant="caption" color="text.secondary" sx={{ mr: 1 }}>
              {new Date(message.created_at.replace(" ", "T") + "Z").toLocaleString("pt-BR")}
            </Typography>
            <Tooltip title="Copiar resposta">
              <IconButton size="small" aria-label="Copiar resposta" onClick={() => copyText(message.content).then(() => notify("Resposta copiada"))}>
                <ContentCopyIcon fontSize="small" />
              </IconButton>
            </Tooltip>
            <Tooltip title="Útil">
              <IconButton size="small" aria-label="Útil" color={vote === true ? "success" : "default"} onClick={() => send(true)}>
                <ThumbUpOutlinedIcon fontSize="small" />
              </IconButton>
            </Tooltip>
            <Tooltip title="Não útil">
              <IconButton size="small" aria-label="Não útil" color={vote === false ? "error" : "default"} onClick={() => setAskReason(true)}>
                <ThumbDownOutlinedIcon fontSize="small" />
              </IconButton>
            </Tooltip>
          </Stack>
        )}
      </Paper>
      {mine && (
        <Avatar sx={{ bgcolor: "secondary.main", width: 32, height: 32 }}>
          <PersonOutlineIcon fontSize="small" />
        </Avatar>
      )}
      <Dialog open={askReason} onClose={() => setAskReason(false)} maxWidth="xs" fullWidth>
        <DialogTitle>Por que a resposta não foi útil?</DialogTitle>
        <DialogContent>
          <RadioGroup value={reason} onChange={(e) => setReason(e.target.value)}>
            {REASONS.map((r) => <FormControlLabel key={r} value={r} control={<Radio size="small" />} label={r} />)}
          </RadioGroup>
          <Box sx={{ mt: 1 }}>
            <TextField label="Comentário (opcional)" multiline minRows={2} value={comment} onChange={(e) => setComment(e.target.value)} />
          </Box>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setAskReason(false)}>Cancelar</Button>
          <Button variant="contained" onClick={() => { setAskReason(false); send(false, reason, comment); }}>Enviar</Button>
        </DialogActions>
      </Dialog>
    </Stack>
  );
}
