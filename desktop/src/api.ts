import { backendInfo, isTauri } from "./native";

export type Script = {
  language: "sql" | "powershell";
  title: string;
  code: string;
  dangerous: boolean;
  reasons: string[];
  warnings: string[];
};

export type Source = {
  chunk_id: number;
  drive_file_id: string;
  source_name: string;
  doc_type: string;
  product: string;
  module: string;
  page: number;
  content: string;
  excerpt: string;
  relevance: number;
  modified_time: string;
  web_url: string;
  path: string;
};

export type Message = {
  id: number;
  case_id: number | null;
  role: "user" | "assistant";
  content: string;
  agent: string;
  sources: Source[];
  meta: { scripts?: Script[]; validation?: string[]; action?: string; llm?: boolean; similar?: Similar[]; [k: string]: unknown };
  created_at: string;
};

export type Fact = { id: number; key: string; value: string; status: "OK" | "FALHA" | "INFO"; source: string; created_at: string };
export type Hypothesis = { id: number; title: string; rationale: string; test: string; status: string; evidence: string; updated_at: string };

export type Case = {
  id: number;
  number: string;
  title: string;
  customer: string;
  product: string;
  module: string;
  routine: string;
  menu: string;
  screen: string;
  error_message: string;
  description: string;
  environment: string;
  server: string;
  database_name: string;
  already_validated: string;
  status: string;
  root_cause: string;
  resolution: string;
  created_at: string;
  updated_at: string;
  facts: Fact[];
  hypotheses: Hypothesis[];
  attachments: { id: number; name: string; size: number; created_at: string }[];
};

export type Similar = { similarity: number; problem: string; previous_cause: string; previous_solution: string; source: string };

export type AiStatus = { online: boolean; provider: string; models: string[]; model: string; embedding_model?: string; error?: string };

export type SystemStatus = {
  version: string;
  backend: string;
  ai: AiStatus;
  drive: { connected: boolean; allowed_folder_id: string; client_secret_configured: boolean };
  rag: { available: boolean; documents: number; chunks: number; vectorized_chunks: number; errors: number };
  index: { last_sync: string; syncing: boolean };
  internet: { enabled: boolean };
  allowed_folder_id: string;
  data_dir: string;
  setup_completed: boolean;
};

export type Job = {
  id: string;
  kind: string;
  state: "running" | "done" | "error";
  done: number;
  total: number;
  percent: number;
  message: string;
  log: string[];
  result: unknown;
  error: string;
};

export type Settings = Record<string, unknown> & {
  theme: "light" | "dark" | "system";
  llm_provider: string;
  embedded_model: string;
  embedded_model_path: string;
  web?: boolean;
  ollama_url: string;
  llm_model: string;
  embedding_model: string;
  openai_base_url: string;
  custom_base_url: string;
  temperature: number;
  google_client_secret_path: string;
  auto_sync_minutes: number;
  internet_enabled: boolean;
  allow_local_execution: boolean;
  update_repo: string;
  chunk_size: number;
  setup_completed: boolean;
  secrets: Record<string, boolean>;
  allowed_folder_id: string;
};

let base: Promise<{ url: string; token: string }> | null = null;
const info = () => (base ??= backendInfo());
let webMode = false;

/** Website login: keep the token for this browser tab only. */
export function setWebToken(token: string) {
  try { sessionStorage.setItem("gv_token", token); } catch { /* storage blocked */ }
  base = null;
}
const localTheme = () => { try { return localStorage.getItem("gv_theme") as Settings["theme"] | null; } catch { return null; } };

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const { url, token } = await info();
  const headers: Record<string, string> = { "x-gv-token": token };
  if (init.body && !(init.body instanceof FormData)) headers["Content-Type"] = "application/json";
  const res = await fetch(`${url}${path}`, { ...init, headers: { ...headers, ...(init.headers as Record<string, string>) } });
  if (!res.ok) {
    if (res.status === 401 && !isTauri) window.dispatchEvent(new Event("gv:login"));
    let detail = `HTTP ${res.status}`;
    try {
      const body = await res.json();
      detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch {
      /* not json */
    }
    throw new ApiError(res.status, detail);
  }
  return res.json() as Promise<T>;
}

const json = (method: string, body?: unknown): RequestInit => ({ method, body: body === undefined ? undefined : JSON.stringify(body) });
const q = (params: Record<string, string | number | boolean | undefined>) =>
  "?" + new URLSearchParams(Object.entries(params).filter(([, v]) => v !== undefined && v !== "").map(([k, v]) => [k, String(v)]));

export const api = {
  health: () => request<{ version: string }>("/health"),
  status: () => request<SystemStatus>("/status"),
  settings: async () => {
    const s = await request<Settings>("/settings");
    webMode = !!s.web;
    if (webMode) s.theme = localTheme() ?? s.theme;
    return s;
  },
  saveSettings: async (changes: Partial<Settings>) => {
    // On the website the theme is each analyst's own; everything else is set by the server administrator.
    if (webMode && Object.keys(changes).every((k) => k === "theme")) {
      try { localStorage.setItem("gv_theme", String(changes.theme)); } catch { /* storage blocked */ }
      return changes as Settings;
    }
    return request<Settings>("/settings", json("PUT", changes));
  },
  login: (password: string) => request<{ token: string }>("/auth/login", json("POST", { password })),
  saveSecret: (name: string, value: string) => request("/settings/secret", json("PUT", { name, value })),
  aiModels: () => request<{ provider: string; models: string[] }>("/ai/models"),
  aiEmbedded: () => request<{ binary: boolean; selected: string; custom_path: string; models: { key: string; label: string; downloaded: boolean }[] }>("/ai/embedded"),
  aiDownloadModel: (key: string) => request<Job>("/ai/embedded/download", json("POST", { text: key })),
  aiImportModel: (path: string) => request<Settings>("/ai/embedded/import", json("POST", { path })),
  aiTest: () => request<{ ok: boolean; answer?: string; seconds?: number; embeddings?: boolean; model?: string; error?: string }>("/ai/test", json("POST")),

  driveStatus: () => request<SystemStatus["drive"]>("/drive/status"),
  driveConnect: (path: string) => request<Job>("/drive/connect", json("POST", { path })),
  driveFolder: () => request<{ id: string; name: string; webViewLink?: string }>("/drive/folder"),
  driveDisconnect: () => request("/drive/disconnect", json("POST")),
  sync: (full = false) => request<Job>(`/sources/sync${q({ full })}`, json("POST")),
  job: (id: string) => request<Job>(`/jobs/${id}`),
  latestJob: (kind: string) => request<Job | Record<string, never>>(`/jobs/latest/${kind}`),

  sourceStats: () => request<{ documents: number; chunks: number; vectorized_chunks: number; by_type: Record<string, number>; by_product: Record<string, number>; errors: number; last_sync: string; most_used: { drive_file_id: string; name: string; uses: number }[] }>("/sources/stats"),
  sources: (params: { q?: string; doc_type?: string; product?: string }) =>
    request<{ drive_file_id: string; name: string; path: string; doc_type: string; product: string; module: string; modified_time: string; chunks: number; web_url: string }[]>(`/sources${q(params)}`),
  sourceErrors: () => request<{ id: number; name: string; error: string; created_at: string }[]>("/sources/errors"),
  search: (query: string, filters: { product?: string; doc_type?: string } = {}) => request<Source[]>(`/sources/search${q({ q: query, ...filters })}`),
  sourceChunks: (id: string) => request<{ source: Record<string, string>; chunks: { id: number; page: number; content: string }[] }>(`/sources/${id}/chunks`),

  dashboard: () => request<{ investigated: number; in_progress: number; solved: number; escalated: number; sources: number; last_sync: string; ai: AiStatus; recent_cases: Case[]; recent_investigations: (Case & { last_message: string })[]; most_used: { drive_file_id: string; name: string; uses: number }[] }>("/dashboard"),
  cases: (status = "", query = "") => request<Case[]>(`/cases${q({ status, q: query })}`),
  createCase: (data: Partial<Case>) => request<Case>("/cases", json("POST", data)),
  getCase: (id: number) => request<Case>(`/cases/${id}`),
  patchCase: (id: number, data: Partial<Case>) => request<Case>(`/cases/${id}`, json("PATCH", data)),
  deleteCase: (id: number) => request(`/cases/${id}`, json("DELETE")),
  investigate: (id: number, message: string, action = "investigar") =>
    request<{ message: Message; case: Case }>(`/cases/${id}/investigate`, json("POST", { message, action })),
  caseMessages: (id: number) => request<Message[]>(`/cases/${id}/messages`),
  addFact: (id: number, key: string, value: string, status = "") => request<Fact>(`/cases/${id}/facts`, json("POST", { key, value, status })),
  deleteFact: (id: number) => request(`/facts/${id}`, json("DELETE")),
  addHypothesis: (id: number, title: string) => request<Hypothesis>(`/cases/${id}/hypotheses`, json("POST", { title })),
  patchHypothesis: (id: number, data: Partial<Hypothesis>) => request<Hypothesis>(`/hypotheses/${id}`, json("PATCH", data)),
  uploadAttachment: (id: number, file: File) => {
    const fd = new FormData();
    fd.append("file", file);
    return request<{ id: number; name: string; has_text: boolean }>(`/cases/${id}/attachments`, { method: "POST", body: fd });
  },

  chatMessages: () => request<Message[]>("/chat/messages"),
  chat: (message: string, use_sources = true) => request<{ message: Message }>("/chat", json("POST", { message, use_sources })),
  chatUpload: (file: File, message: string) => {
    const fd = new FormData();
    fd.append("file", file);
    fd.append("message", message);
    return request<{ message: Message }>("/chat/upload", { method: "POST", body: fd });
  },
  clearChat: () => request("/chat/messages", json("DELETE")),
  feedback: (messageId: number, useful: boolean, reason = "", comment = "") =>
    request(`/messages/${messageId}/feedback`, json("POST", { useful, reason, comment })),

  sqlDiscovery: (term: string) => request<Script>("/tools/sql", json("POST", { term })),
  sqlCorrection: (data: { table: string; where: string; set_clause: string; delete: boolean }) => request<Script>("/tools/sql/correction", json("POST", data)),
  sqlCheck: (text: string) => request<Script[]>("/tools/sql/check", json("POST", { text })),
  psModules: () => request<{ id: string; label: string }[]>("/tools/powershell/modules"),
  powershell: (data: { modules: string[]; target: string; sql_instance: string; urls: string[]; log_path: string; hours: number }) =>
    request<Script>("/tools/powershell", json("POST", data)),
  analyzeLog: (input: File | string) => {
    const fd = new FormData();
    if (typeof input === "string") fd.append("text", input);
    else fd.append("file", input);
    return request<{ markdown: string; result: Record<string, unknown> }>("/tools/log", { method: "POST", body: fd });
  },
  similar: (text: string) => request<{ content: string; meta: { similar?: Similar[] } }>("/tools/similar", json("POST", { text })),
  compare: (a: string, b: string, name_a: string, name_b: string) =>
    request<{ similarity: number; diff: string; added: number; removed: number }>("/tools/compare", json("POST", { a, b, name_a, name_b })),
  execute: (script: string) => request<{ exit_code: number; stdout: string; stderr: string }>("/tools/execute", json("POST", { script })),

  backupExport: () => request<{ path: string }>("/backup/export", json("POST")),
  backupImport: (path: string) => request<{ restored: boolean; safety_backup: string }>("/backup/import", json("POST", { path })),
  updates: () => request<{ current: string; latest: string; available: boolean; url: string; notes: string; error: string }>("/updates/check"),
  logsPath: () => request<{ path: string }>("/logs/path"),
};

export async function waitForBackend(timeoutMs = 30000): Promise<boolean> {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    try {
      await api.health();
      return true;
    } catch {
      await new Promise((r) => setTimeout(r, 400));
    }
  }
  return false;
}

export async function pollJob(id: string, onUpdate: (job: Job) => void): Promise<Job> {
  for (;;) {
    const job = await api.job(id);
    onUpdate(job);
    if (job.state !== "running") return job;
    await new Promise((r) => setTimeout(r, 800));
  }
}
