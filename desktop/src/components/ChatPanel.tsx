import { useEffect, useRef, useState, type ReactNode } from "react";
import { Box, Button, Chip, IconButton, LinearProgress, Stack, TextField, Tooltip, Typography } from "@mui/material";
import SendIcon from "@mui/icons-material/Send";
import AttachFileIcon from "@mui/icons-material/AttachFile";
import type { Message } from "../api";
import MessageView from "./MessageView";
import { DropZone } from "./common";

export const QUICK_ACTIONS: [string, string][] = [
  ["investigar", "Investigar"], ["pesquisar_fontes", "Pesquisar fontes"], ["gerar_sql", "Gerar SQL"],
  ["gerar_powershell", "Gerar PowerShell"], ["analisar_log", "Analisar log"], ["caso_semelhante", "Buscar caso semelhante"],
  ["interpretar_resultado", "Interpretar resultado"], ["responder_cliente", "Responder cliente"], ["escalonar_n3", "Escalonar N3"],
];

/** Shared conversation surface for the case view and the free chat. Ctrl+Enter sends. */
export default function ChatPanel({
  messages, busy, onSend, onFiles, onAction, placeholder, empty, toolbar,
}: {
  messages: Message[];
  busy: boolean;
  onSend: (text: string) => Promise<void> | void;
  onFiles?: (files: File[], text: string) => void;
  onAction?: (action: string, text: string) => void;
  placeholder?: string;
  empty?: ReactNode;
  toolbar?: ReactNode;
}) {
  const [text, setText] = useState("");
  const end = useRef<HTMLDivElement>(null);
  const last = useRef<HTMLDivElement>(null);
  const input = useRef<HTMLTextAreaElement>(null);
  // Long answers (scripts) scroll to their first line, not their end, so the analyst reads the conclusion first.
  useEffect(() => (busy ? end.current : last.current ?? end.current)?.scrollIntoView({ behavior: "smooth", block: busy ? "end" : "start" }), [messages.length, busy]);
  useEffect(() => {
    const focus = () => input.current?.focus();
    window.addEventListener("gv:focus-input", focus);
    return () => window.removeEventListener("gv:focus-input", focus);
  }, []);

  const send = async () => {
    const t = text.trim();
    if (!t || busy) return;
    setText("");
    await onSend(t);
  };
  const files = (f: File[]) => { if (onFiles) { onFiles(f, text.trim()); setText(""); } };

  return (
    <DropZone onFiles={files} label="Solte o arquivo para analisar">
      <Box sx={{ flex: 1, minHeight: 0, overflowY: "auto", p: 2 }} aria-live="polite">
        {messages.length === 0 && !busy && empty}
        {messages.map((m, i) => <div key={m.id} ref={i === messages.length - 1 ? last : undefined}><MessageView message={m} /></div>)}
        {busy && (
          <Box sx={{ maxWidth: 420, mb: 2 }}>
            <Typography variant="body2" color="text.secondary" sx={{ mb: 0.5 }}>Analisando com os agentes…</Typography>
            <LinearProgress />
          </Box>
        )}
        <div ref={end} />
      </Box>
      <Box sx={{ borderTop: 1, borderColor: "divider", p: 1.5, bgcolor: "background.paper" }}>
        {toolbar}
        {onAction && (
          <Stack direction="row" spacing={0.75} sx={{ flexWrap: "wrap", rowGap: 0.75, mb: 1 }}>
            {QUICK_ACTIONS.map(([id, label]) => (
              <Chip key={id} label={label} size="small" variant="outlined" color="primary" disabled={busy}
                onClick={() => { onAction(id, text.trim()); setText(""); }} />
            ))}
          </Stack>
        )}
        <Stack direction="row" spacing={1} sx={{ alignItems: "flex-end" }}>
          {onFiles && (
            <Tooltip title="Anexar arquivo (log, print, PDF…)">
              <IconButton component="label" aria-label="Anexar arquivo" disabled={busy}>
                <AttachFileIcon />
                <input hidden type="file" multiple onChange={(e) => { files(Array.from(e.target.files ?? [])); e.target.value = ""; }} />
              </IconButton>
            </Tooltip>
          )}
          <TextField
            inputRef={input}
            multiline
            maxRows={8}
            value={text}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) { e.preventDefault(); send(); } }}
            placeholder={placeholder ?? "Descreva o que precisa… (Ctrl+Enter para enviar)"}
            slotProps={{ htmlInput: { "aria-label": "Mensagem" } }}
          />
          <Button variant="contained" onClick={send} disabled={!text.trim()} loading={busy} endIcon={<SendIcon />} sx={{ flexShrink: 0 }}>
            Enviar
          </Button>
        </Stack>
      </Box>
    </DropZone>
  );
}
