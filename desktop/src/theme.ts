/**
 * GV Dasa Design System tokens (SharePoint "Design System" > Cores / App Bar / Button / Componentes).
 * Base: Material UI with the GV Dasa palette. Dark mode is an adaptation (the DS publishes no dark palette):
 * same brand hues, MUI dark surfaces.
 */
import { createTheme, type PaletteMode } from "@mui/material/styles";

export const gv = {
  primary: { light: "#339F9A", main: "#018781", dark: "#005E5A", contrastText: "#FFFFFF" },
  secondary: { light: "#33C7BD", main: "#00B9AD", dark: "#008179", contrastText: "#FFFFFF" },
  success: "#2E7D32",
  error: "#D32F2F",
  warning: "#ED6C02",
  info: "#0288D1",
  grey: { 50: "#FAFAFA", 100: "#F5F5F5", 200: "#EEEEEE", 300: "#E0E0E0", 400: "#BDBDBD", 500: "#9E9E9E", 600: "#757575", 700: "#616161", 800: "#323232" },
  mint: "#E1FFF6", // brand background tint
  divider: "rgba(0, 0, 0, 0.12)",
  tertiary: { tealLighten1: "#A8F6D6", cyanLighten1: "#BCF7FF", yellow: "#FFB400", amberLighten: "#F8E29A", redLighten: "#FFB2CC" },
};

export function buildTheme(mode: PaletteMode) {
  const dark = mode === "dark";
  return createTheme({
    palette: {
      mode,
      primary: dark ? { ...gv.primary, main: gv.primary.light } : gv.primary,
      secondary: gv.secondary,
      success: { main: gv.success },
      error: { main: gv.error },
      warning: { main: gv.warning },
      info: { main: gv.info },
      grey: gv.grey,
      divider: dark ? "rgba(255,255,255,0.12)" : gv.divider,
      background: dark ? { default: "#121414", paper: "#1C1F1F" } : { default: "#F7F7F7", paper: "#FFFFFF" },
      ...(dark ? {} : { text: { primary: "rgba(0,0,0,0.87)", secondary: "rgba(0,0,0,0.6)", disabled: "rgba(0,0,0,0.38)" },
      action: {
        active: "rgba(0,0,0,0.54)", hover: "rgba(0,0,0,0.04)", selected: "rgba(1,135,129,0.08)",
        focus: "rgba(0,0,0,0.12)", disabled: "rgba(0,0,0,0.26)", disabledBackground: "rgba(0,0,0,0.12)",
      } }),
    },
    typography: {
      fontFamily: '"Roboto", "Segoe UI", Arial, sans-serif',
      h5: { fontWeight: 500, fontSize: "1.375rem" },
      h6: { fontWeight: 500, fontSize: "1.125rem" },
      subtitle1: { fontWeight: 700, fontSize: "1rem" }, // Body 1 Bold - page title in App Bar
      button: { textTransform: "none", fontWeight: 500 }, // DS: sentence case ("Salvar")
    },
    shape: { borderRadius: 4 },
    components: {
      MuiAppBar: { defaultProps: { elevation: 0 } }, // DS: App Bar elevation 0
      MuiButton: { defaultProps: { disableElevation: true } },
      MuiPaper: { defaultProps: { elevation: 0 }, styleOverrides: { root: { backgroundImage: "none" } } },
      MuiCard: { defaultProps: { variant: "outlined" } },
      MuiTextField: { defaultProps: { size: "small", fullWidth: true } },
      MuiSelect: { defaultProps: { size: "small" } },
      MuiTooltip: { defaultProps: { arrow: true, enterDelay: 400 } },
      MuiTab: { styleOverrides: { root: { textTransform: "none", minHeight: 44 } } },
      MuiCssBaseline: {
        styleOverrides: {
          "*:focus-visible": { outline: `2px solid ${gv.secondary.main}`, outlineOffset: 2 },
          "::-webkit-scrollbar": { width: 10, height: 10 },
          "::-webkit-scrollbar-thumb": { background: dark ? "#3a3f3f" : gv.grey[400], borderRadius: 5 },
        },
      },
    },
  });
}
