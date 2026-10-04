import { useState, type ReactNode } from "react";
import { Box, Chip, Stack, Typography } from "@mui/material";
import UploadFileIcon from "@mui/icons-material/UploadFile";
import { caseStatusColor, hypothesisColor } from "../theme";

/** DS "Estrutura de página": title + actions aligned right. */
export function PageHeader({ title, subtitle, actions }: { title: string; subtitle?: string; actions?: ReactNode }) {
  return (
    <Stack direction="row" spacing={2} sx={{ alignItems: "center", mb: 2.5, flexWrap: "wrap", rowGap: 1 }}>
      <Box sx={{ flex: 1, minWidth: 240 }}>
        <Typography variant="h5" component="h1">{title}</Typography>
        {subtitle && <Typography variant="body2" color="text.secondary">{subtitle}</Typography>}
      </Box>
      {actions && <Stack direction="row" spacing={1} sx={{ flexWrap: "wrap", rowGap: 1 }}>{actions}</Stack>}
    </Stack>
  );
}

export function CaseStatusChip({ status }: { status: string }) {
  return <Chip size="small" label={status} color={caseStatusColor[status] ?? "default"} />;
}

export function HypothesisChip({ status }: { status: string }) {
  return <Chip size="small" label={status.toUpperCase()} color={hypothesisColor[status] ?? "default"} variant={status === "Não validada" ? "outlined" : "filled"} sx={{ fontWeight: 600, fontSize: 11 }} />;
}

export function formatDate(value?: string) {
  if (!value) return "-";
  const d = new Date(value.includes("T") ? value : value.replace(" ", "T") + "Z");
  return isNaN(d.getTime()) ? value : d.toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "short" });
}

/** Drag & drop from Windows Explorer (HTML5; Tauri's native drag handler is disabled in tauri.conf.json). */
export function DropZone({ onFiles, children, label = "Solte arquivos aqui" }: { onFiles: (files: File[]) => void; children: ReactNode; label?: string }) {
  const [over, setOver] = useState(false);
  return (
    <Box
      onDragOver={(e) => { if (e.dataTransfer.types.includes("Files")) { e.preventDefault(); setOver(true); } }}
      onDragLeave={(e) => { if (e.currentTarget === e.target) setOver(false); }}
      onDrop={(e) => { e.preventDefault(); setOver(false); const files = Array.from(e.dataTransfer.files); if (files.length) onFiles(files); }}
      sx={{ position: "relative", height: "100%", minHeight: 0, display: "flex", flexDirection: "column" }}
    >
      {children}
      {over && (
        <Stack sx={{ position: "absolute", inset: 0, zIndex: 10, alignItems: "center", justifyContent: "center", bgcolor: "rgba(1,135,129,0.12)",
                     border: 2, borderStyle: "dashed", borderColor: "primary.main", borderRadius: 1, pointerEvents: "none" }}>
          <UploadFileIcon color="primary" sx={{ fontSize: 48 }} />
          <Typography color="primary" sx={{ fontWeight: 600 }}>{label}</Typography>
        </Stack>
      )}
    </Box>
  );
}

export function StatCard({ label, value, icon, hint }: { label: string; value: ReactNode; icon: ReactNode; hint?: string }) {
  return (
    <Box sx={{ p: 2, border: 1, borderColor: "divider", borderRadius: 1, bgcolor: "background.paper", display: "flex", gap: 1.5, alignItems: "center", minWidth: 0 }}>
      <Box sx={{ width: 44, height: 44, borderRadius: "50%", display: "grid", placeItems: "center", bgcolor: "action.selected", color: "primary.main", flexShrink: 0 }}>
        {icon}
      </Box>
      <Box sx={{ minWidth: 0 }}>
        <Typography variant="body2" color="text.secondary" sx={{ lineHeight: 1.25 }}>{label}</Typography>
        <Typography variant="h6" sx={{ lineHeight: 1.2 }} noWrap>{value}</Typography>
        {hint && <Typography variant="caption" color="text.secondary" noWrap sx={{ display: "block" }}>{hint}</Typography>}
      </Box>
    </Box>
  );
}
