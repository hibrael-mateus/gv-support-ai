import { useMemo, useState } from "react";
import { Alert, Box, Button, Chip, Stack, Tooltip, Typography } from "@mui/material";
import ContentCopyIcon from "@mui/icons-material/ContentCopy";
import SaveAltIcon from "@mui/icons-material/SaveAlt";
import WarningAmberIcon from "@mui/icons-material/WarningAmber";
import hljs from "highlight.js/lib/core";
import sql from "highlight.js/lib/languages/sql";
import powershell from "highlight.js/lib/languages/powershell";
import xml from "highlight.js/lib/languages/xml";
import jsonLang from "highlight.js/lib/languages/json";
import diff from "highlight.js/lib/languages/diff";
import "highlight.js/styles/github-dark.css";
import { copyText, saveTextFile } from "../native";
import { useNotify } from "./notify";

hljs.registerLanguage("sql", sql);
hljs.registerLanguage("powershell", powershell);
hljs.registerLanguage("xml", xml);
hljs.registerLanguage("json", jsonLang);
hljs.registerLanguage("diff", diff);
hljs.registerAliases(["ps1", "ps", "pwsh"], { languageName: "powershell" });
hljs.registerAliases(["tsql", "mssql"], { languageName: "sql" });

// Mirrors backend app/security.py danger rules so every code block (also inside Markdown) is flagged.
const SQL_DANGER: [RegExp, string][] = [
  [/\bDELETE\b/i, "DELETE remove registros"],
  [/\bUPDATE\b/i, "UPDATE altera registros"],
  [/\bDROP\b/i, "DROP remove objetos"],
  [/\bTRUNCATE\b/i, "TRUNCATE apaga todos os registros"],
  [/\bALTER\b/i, "ALTER altera estrutura"],
  [/\bMERGE\b/i, "MERGE altera registros"],
  [/\bINSERT\b/i, "INSERT inclui registros"],
  [/\bEXEC(UTE)?\b/i, "EXEC executa procedure"],
];
const PS_DANGER: [RegExp, string][] = [
  [/\bRemove-Item\b/i, "remove arquivos ou pastas"],
  [/\bStop-Service\b/i, "para serviço"],
  [/\bRestart-Service\b/i, "reinicia serviço"],
  [/\bStop-Process\b/i, "encerra processo"],
  [/\b(Restart|Stop)-Computer\b/i, "reinicia/desliga o servidor"],
  [/\b(Stop|Restart)-WebAppPool\b|\bStop-Website\b/i, "interrompe IIS"],
  [/\b(Set|Clear|Disable|Uninstall)-\w+/i, "altera configuração do sistema"],
];

export function classify(language: string, code: string): string[] {
  if (/^(sql|tsql|mssql)$/i.test(language)) {
    const body = code.replace(/--[^\n]*|\/\*[\s\S]*?\*\//g, " ").replace(/'(?:''|[^'])*'/g, "''");
    return SQL_DANGER.filter(([re]) => re.test(body)).map(([, why]) => why);
  }
  if (/^(powershell|ps1|ps|pwsh)$/i.test(language)) {
    const body = code.replace(/<#[\s\S]*?#>|#[^\n]*/g, " ").replace(/"(?:`.|[^"])*"|'(?:''|[^'])*'/g, "''");
    return [...new Set(PS_DANGER.filter(([re]) => re.test(body)).map(([, why]) => why))];
  }
  return [];
}

type Props = { code: string; language?: string; title?: string; reasons?: string[]; warnings?: string[]; maxHeight?: number };

export default function CodeBlock({ code, language = "", title, reasons, warnings = [], maxHeight = 480 }: Props) {
  const notify = useNotify();
  const [busy, setBusy] = useState(false);
  const lang = language.toLowerCase();
  const isSql = /^(sql|tsql|mssql)$/.test(lang);
  const isPs = /^(powershell|ps1|ps|pwsh)$/.test(lang);
  const danger = reasons ?? classify(lang, code);
  const html = useMemo(() => {
    try {
      return hljs.getLanguage(lang) ? hljs.highlight(code, { language: lang }).value : hljs.highlightAuto(code).value;
    } catch {
      return code.replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" })[c]!);
    }
  }, [code, lang]);

  const copy = async () => {
    await copyText(code);
    notify(isSql ? "SQL copiado" : isPs ? "PowerShell copiado" : "Copiado");
  };
  const save = async () => {
    setBusy(true);
    try {
      const ext = isSql ? "sql" : "ps1";
      const stamp = new Date().toISOString().slice(0, 19).replace(/[-:T]/g, "");
      const path = await saveTextFile(`gv-support-${stamp}.${ext}`, code, ext);
      if (path) notify(`Salvo em ${path}`);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Box
      sx={{
        my: 1.5, borderRadius: 1, overflow: "hidden", border: 2,
        borderColor: danger.length ? "error.main" : "divider",
      }}
    >
      <Stack direction="row" spacing={1} sx={{ alignItems: "center", px: 1.5, py: 0.5, bgcolor: danger.length ? "error.main" : "grey.800", color: "#fff", flexWrap: "wrap" }}>
        {danger.length > 0 && <WarningAmberIcon fontSize="small" />}
        <Typography variant="caption" sx={{ fontWeight: 700, flex: 1, minWidth: 120 }}>
          {title || (isSql ? "SQL" : isPs ? "PowerShell" : lang.toUpperCase() || "Código")}
          {danger.length > 0 && " — SCRIPT PERIGOSO: revise antes de executar"}
        </Typography>
        {isSql && <Chip size="small" label="SQL Server" sx={{ color: "#fff", bgcolor: "rgba(255,255,255,0.15)" }} />}
        <Tooltip title={isSql ? "Copiar SQL" : isPs ? "Copiar PowerShell" : "Copiar"}>
          <Button size="small" onClick={copy} startIcon={<ContentCopyIcon />} sx={{ color: "#fff" }}>
            {isSql ? "Copiar SQL" : isPs ? "Copiar PowerShell" : "Copiar"}
          </Button>
        </Tooltip>
        {(isSql || isPs) && (
          <Button size="small" onClick={save} disabled={busy} startIcon={<SaveAltIcon />} sx={{ color: "#fff" }}>
            {isSql ? "Salvar .sql" : "Salvar .ps1"}
          </Button>
        )}
      </Stack>
      {(danger.length > 0 || warnings.length > 0) && (
        <Alert severity={danger.length ? "error" : "warning"} sx={{ borderRadius: 0 }}>
          {danger.length > 0 && <>Contém: {danger.join("; ")}. Nunca é executado automaticamente.</>}
          {warnings.map((w) => <div key={w}>{w}</div>)}
        </Alert>
      )}
      <Box
        component="pre"
        sx={{ m: 0, p: 1.5, maxHeight, overflow: "auto", bgcolor: "#0d1117", color: "#e6edf3", fontSize: 12.5, lineHeight: 1.5, fontFamily: '"Cascadia Code", Consolas, monospace' }}
      >
        <code className="hljs" dangerouslySetInnerHTML={{ __html: html }} />
      </Box>
    </Box>
  );
}
