import { useEffect, useState } from "react";
import { Box, Button, FormControlLabel, Paper, Stack, Switch, Typography } from "@mui/material";
import DeleteSweepOutlinedIcon from "@mui/icons-material/DeleteSweepOutlined";
import { api, type Message } from "../api";
import ChatPanel from "../components/ChatPanel";
import { PageHeader } from "../components/common";
import { errorText, useNotify } from "../components/notify";

const EXAMPLES = [
  "Como funciona o cálculo de média no GVcollege?",
  "Gere um diagnóstico PowerShell de IIS e certificados",
  "O que significa o erro 'Timeout expired' do SQL Server?",
];

export default function Chat() {
  const notify = useNotify();
  const [messages, setMessages] = useState<Message[]>([]);
  const [busy, setBusy] = useState(false);
  const [useSources, setUseSources] = useState(true);

  useEffect(() => { api.chatMessages().then(setMessages).catch((e) => notify(errorText(e), "error")); }, [notify]);

  const clear = async () => {
    try { await api.clearChat(); setMessages([]); } catch (e) { notify(errorText(e), "error"); }
  };
  useEffect(() => {
    window.addEventListener("gv:clear-chat", clear);
    return () => window.removeEventListener("gv:clear-chat", clear);
  });

  const exec = async (fn: () => Promise<{ message: Message }>, userText: string) => {
    setBusy(true);
    setMessages((m) => [...m, { id: -Date.now(), case_id: null, role: "user", content: userText, agent: "", sources: [], meta: {}, created_at: new Date().toISOString().replace("Z", "") }]);
    try {
      await fn();
      setMessages(await api.chatMessages());
    } catch (e) {
      notify(errorText(e), "error");
    } finally {
      setBusy(false);
    }
  };

  const send = (t: string) => exec(() => api.chat(t, useSources), t);
  const files = async (fs: File[], t: string) => {
    for (const f of fs) await exec(() => api.chatUpload(f, t), `📎 ${f.name}${t ? `\n${t}` : ""}`);
  };

  return (
    <Box sx={{ display: "flex", flexDirection: "column", height: "100%", minHeight: 0 }}>
      <PageHeader
        title="Chat"
        subtitle="Perguntas rápidas fora de um chamado. Respostas GV Dasa sempre citam as fontes."
        actions={
          <>
            <FormControlLabel control={<Switch checked={useSources} onChange={(e) => setUseSources(e.target.checked)} />} label="Consultar fontes GV Dasa" />
            <Button variant="outlined" startIcon={<DeleteSweepOutlinedIcon />} onClick={clear}>Limpar conversa</Button>
          </>
        }
      />
      <Paper variant="outlined" sx={{ flex: 1, minHeight: 0, display: "flex", flexDirection: "column", overflow: "hidden" }}>
        <ChatPanel
          messages={messages}
          busy={busy}
          onSend={send}
          onFiles={files}
          empty={
            <Stack spacing={1} sx={{ alignItems: "flex-start" }}>
              <Typography color="text.secondary">Experimente perguntar:</Typography>
              {EXAMPLES.map((e) => <Button key={e} variant="outlined" size="small" onClick={() => send(e)}>{e}</Button>)}
              <Typography variant="caption" color="text.secondary">Arraste um log, PDF ou planilha para analisar. Ctrl+L limpa a conversa.</Typography>
            </Stack>
          }
        />
      </Paper>
    </Box>
  );
}
