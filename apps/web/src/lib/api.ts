// The only place that talks to the backend.

export type ClipStatus = "processing" | "done" | "failed";

export interface Clip {
  id: string;
  name: string | null;
  start: string;
  created: string;
  seconds: number;
  windows: number | null;
  described: number | null;
  status: ClipStatus;
  processed_s: number | null;
  actions?: number;
  objects?: number;
  questions?: number;
}

export interface DiaryRow {
  start: string;
  end: string;
  verb: string | null;
  object: string | null;
  where: string | null;
  place: string | null;
  source: string | null;
  line: string;
  offset_s?: number;
  state?: { object: string; state: string }[];
}

export interface Moment { start: string; end: string; what: string }

export interface AskResult {
  id: number | null;
  answer: string;
  kind: string;
  moment: Moment | null;
  evidence: DiaryRow[];
  latency_ms: number;
  degraded: boolean;
  read_as?: string | null;
}

export interface QuestionRecord {
  id: number;
  asked_at: string;
  question: string;
  answer: string;
  kind: string | null;
  clip_id: string | null;
  as_of: string | null;
  moment: string | null;
  evidence: DiaryRow[];
  latency_ms: number | null;
}

export interface Overview {
  recordings: number;
  recorded_seconds: number;
  processing: number;
  diary_lines: number;
  objects: number;
  questions: number;
  last_activity: string | null;
  top_objects: { object: string; count: number }[];
  top_actions: { verb: string; count: number }[];
}

export interface Alert { object: string; state: string; since: string }

export interface ObjectRecord {
  object: string;
  count: number;
  first: string;
  last: string;
  last_action: string;
  where: string | null;
  state: string | null;
}

export type ServiceHealth = string | Record<string, unknown>;

export interface Health {
  backend: string;
  database: string;
  big_model: ServiceHealth;
  small_model: ServiceHealth;
}

export interface TableStat { table: string; rows: number; bytes: number | null }

export interface SystemInfo {
  backend: { status: string; started: string; uptime_s: number; search: string;
             jobs: Record<"queued" | "running" | "done" | "failed", number> };
  database: { engine: string; database?: string; bytes?: number; tables: TableStat[]; views?: string[]; error?: string };
  small_model: { status: ServiceHealth; url: string; name: string };
  big_model: { status: ServiceHealth; name: string };
}

export interface TablePage { table: string; columns: string[]; rows: unknown[][]; total: number }

export interface Job {
  status: "queued" | "running" | "done" | "failed";
  step?: string;
  error?: string;
  progress?: { processed_s: number; seconds: number };
}

// App token: set when the backend is reachable from outside this laptop. Opened once as ...?token=XYZ, then remembered.
const urlToken = new URLSearchParams(location.search).get("token");
try { if (urlToken) localStorage.setItem("mnemo_token", urlToken); } catch { /* private window */ }
function token(): string {
  if (urlToken) return urlToken;
  try { return localStorage.getItem("mnemo_token") ?? ""; } catch { return ""; }
}
const auth = (): Record<string, string> => (token() ? { "X-Engram-Token": token() } : {});

export async function get<T>(path: string): Promise<T> {
  const r = await fetch(path, { headers: auth() });
  if (!r.ok) throw new Error(await reason(r));
  return r.json();
}

async function send<T>(method: string, path: string, body?: unknown): Promise<T> {
  const r = await fetch(path, {
    method,
    headers: { ...auth(), ...(body ? { "Content-Type": "application/json" } : {}) },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!r.ok) throw new Error(await reason(r));
  return r.json();
}

async function reason(r: Response): Promise<string> {
  const body = await r.json().catch(() => null);
  return body?.detail ?? `The backend answered ${r.status}`;
}

export const ask = (question: string, at?: string | null, clipId?: string | null) =>
  send<AskResult>("POST", "/api/ask", { question, at: at ?? null, clip_id: clipId ?? null });
export const deleteClip = (id: string) => send("DELETE", `/api/clips/${id}`);
export const deleteDiary = () => send("DELETE", "/api/diary");

/** Upload with progress (fetch cannot report upload progress). Resolves to the job id, which is also the clip id. */
export function upload(file: File, onProgress: (fraction: number) => void): Promise<string> {
  return new Promise((resolve, reject) => {
    const x = new XMLHttpRequest();
    const form = new FormData();
    form.append("file", file);
    x.open("POST", "/api/clips");
    Object.entries(auth()).forEach(([k, v]) => x.setRequestHeader(k, v));
    x.upload.onprogress = (e) => e.lengthComputable && onProgress(e.loaded / e.total);
    x.onload = () => {
      if (x.status >= 200 && x.status < 300) resolve(JSON.parse(x.responseText).job);
      else reject(new Error(`Upload failed (${x.status})`));
    };
    x.onerror = () => reject(new Error("The backend could not be reached"));
    x.send(form);
  });
}
