/** Thin wrappers over Tauri APIs with browser fallbacks (so `npm run dev` works in a browser too). */
export const isTauri = typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;

export async function backendInfo(): Promise<{ url: string; token: string }> {
  if (isTauri) {
    const { invoke } = await import("@tauri-apps/api/core");
    return invoke("backend_info");
  }
  // Website: same origin, token from the team login. Dev server: local backend.
  const url = import.meta.env.VITE_API_URL ?? (import.meta.env.DEV ? "http://127.0.0.1:8765" : "");
  let token = "";
  try { token = sessionStorage.getItem("gv_token") ?? ""; } catch { /* storage blocked */ }
  return { url, token };
}

export async function saveTextFile(defaultName: string, content: string, ext: string): Promise<string | null> {
  if (isTauri) {
    const { save } = await import("@tauri-apps/plugin-dialog");
    const path = await save({ defaultPath: defaultName, filters: [{ name: ext.toUpperCase(), extensions: [ext] }] });
    if (!path) return null;
    const { invoke } = await import("@tauri-apps/api/core");
    // PowerShell 5.1 needs a BOM to read UTF-8 accents correctly.
    await invoke("write_text_file", { path, contents: content, bom: ext === "ps1" });
    return path;
  }
  const blob = new Blob([ext === "ps1" ? "﻿" + content : content], { type: "text/plain;charset=utf-8" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = defaultName;
  a.click();
  URL.revokeObjectURL(a.href);
  return defaultName;
}

export async function pickFile(extensions: string[], title: string): Promise<string | null> {
  if (!isTauri) return window.prompt(`${title} (caminho completo do arquivo)`);
  const { open } = await import("@tauri-apps/plugin-dialog");
  const result = await open({ multiple: false, directory: false, title, filters: [{ name: "Arquivo", extensions }] });
  return typeof result === "string" ? result : null;
}

export async function openExternal(url: string) {
  if (isTauri) {
    const { openUrl } = await import("@tauri-apps/plugin-opener");
    await openUrl(url);
  } else window.open(url, "_blank", "noopener");
}

export async function revealPath(path: string) {
  if (isTauri) {
    const { revealItemInDir } = await import("@tauri-apps/plugin-opener");
    await revealItemInDir(path);
  }
}

export async function copyText(text: string) {
  await navigator.clipboard.writeText(text);
}
