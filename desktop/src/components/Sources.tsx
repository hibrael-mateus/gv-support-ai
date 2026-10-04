import { useState } from "react";
import {
  Box, Button, Chip, Dialog, DialogActions, DialogContent, DialogTitle, LinearProgress, List, ListItemButton,
  ListItemText, Stack, Typography,
} from "@mui/material";
import DescriptionOutlinedIcon from "@mui/icons-material/DescriptionOutlined";
import OpenInNewIcon from "@mui/icons-material/OpenInNew";
import type { Source } from "../api";
import { openExternal } from "../native";

export function relevanceColor(r: number): "success" | "warning" | "inherit" {
  return r >= 70 ? "success" : r >= 45 ? "warning" : "inherit";
}

/** Sources table: name, type, product, module, page, excerpt, relevance, date. Click shows the exact evidence. */
export function SourceList({ sources, dense = false }: { sources: Source[]; dense?: boolean }) {
  const [open, setOpen] = useState<Source | null>(null);
  if (!sources.length) return null;
  return (
    <>
      <List dense disablePadding>
        {sources.map((s, i) => (
          <ListItemButton key={`${s.chunk_id}-${i}`} onClick={() => setOpen(s)} sx={{ borderRadius: 1, alignItems: "flex-start", gap: 1 }}>
            <DescriptionOutlinedIcon color="primary" fontSize="small" sx={{ mt: 0.5 }} />
            <ListItemText
              primary={
                <Stack direction="row" spacing={1} sx={{ alignItems: "center", flexWrap: "wrap" }}>
                  <Typography variant="body2" sx={{ fontWeight: 600 }}>[F{i + 1}] {s.source_name}</Typography>
                  {s.page > 0 && <Chip size="small" label={`Página ${s.page}`} />}
                  {s.doc_type && <Chip size="small" variant="outlined" label={s.doc_type} />}
                  {s.product && <Chip size="small" variant="outlined" color="primary" label={s.product} />}
                  <Chip size="small" color={relevanceColor(s.relevance) === "inherit" ? "default" : relevanceColor(s.relevance) as "success" | "warning"} label={`Relevância ${Math.round(s.relevance)}%`} />
                </Stack>
              }
              secondary={dense ? undefined : <Typography variant="caption" color="text.secondary" sx={{ display: "block", mt: 0.5 }}>“{s.excerpt}”</Typography>}
            />
          </ListItemButton>
        ))}
      </List>
      <EvidenceDialog source={open} onClose={() => setOpen(null)} />
    </>
  );
}

export function EvidenceDialog({ source, onClose }: { source: Source | null; onClose: () => void }) {
  if (!source) return null;
  const idx = source.content.indexOf(source.excerpt.replace(/…$/, ""));
  const before = idx >= 0 ? source.content.slice(0, idx) : "";
  const hit = idx >= 0 ? source.excerpt.replace(/…$/, "") : "";
  const after = idx >= 0 ? source.content.slice(idx + hit.length) : source.content;
  return (
    <Dialog open onClose={onClose} maxWidth="md" fullWidth>
      <DialogTitle>{source.source_name}</DialogTitle>
      <DialogContent dividers>
        <Stack direction="row" spacing={1} sx={{ mb: 2, flexWrap: "wrap", rowGap: 1 }}>
          <Chip size="small" label={`Tipo: ${source.doc_type || "-"}`} />
          <Chip size="small" label={`Produto: ${source.product || "-"}`} />
          <Chip size="small" label={`Módulo: ${source.module || "-"}`} />
          {source.page > 0 && <Chip size="small" label={`Página ${source.page}`} />}
          {source.modified_time && <Chip size="small" label={`Data: ${new Date(source.modified_time).toLocaleDateString("pt-BR")}`} />}
          {source.path && <Chip size="small" variant="outlined" label={source.path} />}
        </Stack>
        <Typography variant="overline" color="text.secondary">Relevância</Typography>
        <Stack direction="row" spacing={1} sx={{ alignItems: "center", mb: 2 }}>
          <LinearProgress variant="determinate" value={source.relevance} sx={{ flex: 1, height: 8, borderRadius: 4 }} />
          <Typography variant="body2" sx={{ fontWeight: 600 }}>{Math.round(source.relevance)}%</Typography>
        </Stack>
        <Typography variant="overline" color="text.secondary">Trecho utilizado como evidência</Typography>
        <Box sx={{ whiteSpace: "pre-wrap", fontSize: 14, lineHeight: 1.7, p: 2, bgcolor: "action.hover", borderRadius: 1 }}>
          {before}
          <Box component="mark" sx={{ bgcolor: "#FFF7A0", color: "#000", px: 0.25 }}>{hit}</Box>
          {after}
        </Box>
      </DialogContent>
      <DialogActions>
        {source.web_url && (
          <Button startIcon={<OpenInNewIcon />} onClick={() => openExternal(source.web_url)}>Abrir no Google Drive</Button>
        )}
        <Button variant="contained" onClick={onClose}>Fechar</Button>
      </DialogActions>
    </Dialog>
  );
}
