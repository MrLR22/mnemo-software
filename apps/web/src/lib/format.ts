import type { DiaryRow } from "./api";

export const timecode = (s: number) => {
  const t = Math.max(0, Math.floor(s));
  const h = Math.floor(t / 3600);
  const m = Math.floor((t % 3600) / 60);
  const sec = String(t % 60).padStart(2, "0");
  return h ? `${h}:${String(m).padStart(2, "0")}:${sec}` : `${m}:${sec}`;
};

export const clock = (iso: string) =>
  new Date(iso).toLocaleTimeString([], { hour: "numeric", minute: "2-digit", second: "2-digit" });

export const shortClock = (iso: string) => new Date(iso).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });

export const date = (iso: string) => new Date(iso).toLocaleDateString([], { day: "numeric", month: "short", year: "numeric" });

export const dayLabel = (iso: string) =>
  new Date(`${iso.slice(0, 10)}T12:00:00`).toLocaleDateString([], { weekday: "short", day: "numeric", month: "short" });

export const dateTime = (iso: string) =>
  new Date(iso).toLocaleString([], { day: "numeric", month: "short", hour: "numeric", minute: "2-digit" });

export function ago(iso: string): string {
  const s = (Date.now() - new Date(iso).getTime()) / 1000;
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)} min ago`;
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`;
  return `${Math.floor(s / 86400)} d ago`;
}

export const duration = (s: number) => {
  if (s < 60) return `${Math.round(s)} s`;
  if (s < 3600) return `${Math.floor(s / 60)} min ${String(Math.round(s % 60)).padStart(2, "0")} s`;
  return `${Math.floor(s / 3600)} h ${Math.round((s % 3600) / 60)} min`;
};

export const bytes = (n: number | null | undefined) => {
  if (n == null) return "–";
  if (n < 1024) return `${n} B`;
  if (n < 1024 ** 2) return `${(n / 1024).toFixed(0)} kB`;
  return `${(n / 1024 ** 2).toFixed(1)} MB`;
};

export const capital = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);

/** Local time as the backend expects it (no time zone). */
export function localIso(d: Date): string {
  return new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 19);
}

export type ActionKind = "state" | "handle" | "use";

export function actionKind(verb: string | null): ActionKind {
  const v = (verb ?? "").trim();
  if (["opens", "closes", "turns on", "turns off"].includes(v)) return "state";
  if (/^(picks? up|puts? down|takes?|places?|moves?|holds?)/.test(v)) return "handle";
  return "use";
}

/** Rows that started in the same 4-second window, in order. */
export interface Moment { offset: number; length: number; rows: DiaryRow[] }

export function groupByMoment(rows: DiaryRow[]): Moment[] {
  const out: Moment[] = [];
  for (const r of rows) {
    const offset = r.offset_s ?? 0;
    const last = out[out.length - 1];
    if (last && last.offset === offset) last.rows.push(r);
    else out.push({ offset, length: Math.max(1, (new Date(r.end).getTime() - new Date(r.start).getTime()) / 1000), rows: [r] });
  }
  return out;
}

export const answerRoute: Record<string, string> = {
  count: "Counted from the diary",
  state: "Object-state memory",
  llm: "Diary search + language model",
  search: "Matching diary lines",
  none: "No records",
};

/** Questions that this diary can really answer, built from what is in it. */
export function suggestions(rows: DiaryRow[], max = 3): string[] {
  const base = (v: string) => v.trim().replace(/^(\w+?)(es|s)?\b/, (_, w: string, e?: string) => (e === "es" && /(ss|sh|ch|x)$/.test(w) ? w : w + (e === "es" ? "e" : "")));
  const out: string[] = [];
  const stateful = rows.find((r) => r.state?.some((s) => s.state === "open" || s.state === "closed"));
  if (stateful?.state?.[0]) out.push(`Did I close the ${stateful.state[0].object}?`);
  const power = rows.find((r) => r.state?.some((s) => s.state === "on" || s.state === "off"));
  if (power?.state?.[0]) out.push(`Is the ${power.state[0].object} still on?`);
  const counts = new Map<string, { n: number; r: DiaryRow }>();
  for (const r of rows) {
    if (!r.verb || !r.object) continue;
    const k = `${r.verb}|${r.object}`;
    counts.set(k, { n: (counts.get(k)?.n ?? 0) + 1, r });
  }
  const top = [...counts.values()].sort((a, b) => b.n - a.n)[0];
  if (top) out.push(`How many times did I ${base(top.r.verb!)} the ${top.r.object}?`);
  const placed = [...rows].reverse().find((r) => r.where && r.object && /picks? up|puts? down/.test(r.verb ?? ""));
  if (placed) out.push(`Where did I put the ${placed.object}?`);
  return out.slice(0, max);
}
