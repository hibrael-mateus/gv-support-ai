import { createContext, useCallback, useContext, useState, type ReactNode } from "react";
import { Alert, Snackbar } from "@mui/material";

type Severity = "success" | "info" | "warning" | "error";
const Ctx = createContext<(msg: string, severity?: Severity) => void>(() => {});

export function NotifyProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<{ msg: string; severity: Severity; key: number } | null>(null);
  const notify = useCallback((msg: string, severity: Severity = "success") => setState({ msg, severity, key: Date.now() }), []);
  return (
    <Ctx.Provider value={notify}>
      {children}
      <Snackbar key={state?.key} open={!!state} autoHideDuration={4500} onClose={() => setState(null)} anchorOrigin={{ vertical: "bottom", horizontal: "right" }}>
        <Alert severity={state?.severity ?? "info"} variant="filled" onClose={() => setState(null)} sx={{ maxWidth: 520 }}>
          {state?.msg}
        </Alert>
      </Snackbar>
    </Ctx.Provider>
  );
}

export const useNotify = () => useContext(Ctx);

export function errorText(e: unknown) {
  return e instanceof Error ? e.message : String(e);
}
