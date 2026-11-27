/* Types and helpers shared by the dashboard. Data shapes follow the gateway's
 * JSON (Gateway/src/decode.cpp) plus the fields the backend adds (ts, risk). */

export type Sc1 = {
  vbat_v: number;
  ibat_ma: number;
  soc: number;
  status: number;
  cell_c: number | null;
  soil_c: number | null;
  soil_pct: number | null;
  borer: number;
  rain_mm: { "1h": number; "24h": number; "3d": number; "5d": number; "7d": number; "15d": number };
  alerts: { rain: boolean; low_batt: boolean; borer: boolean };
};

export type Report = {
  node: number;
  seq: number;
  type: "report" | "logging_alert" | "tilt_alert" | "boot" | "sc1_alert" | string;
  rssi: number;
  snr: number;
  flags?: { charge_temp: boolean; sensor_fault: boolean };
  buzz: number;
  bird: number;
  saw: number;
  tilt_x: number;
  tilt_y: number;
  temp_c: number;
  rh: number;
  press_hpa: number;
  sc1?: Sc1;
  ts: number;
  risk: number | null;
  demo?: boolean;
  verified?: boolean;
  auth?: { epoch: number; counter: number };
};

export type SecurityEvent = { ts: number; node: number | null; reason: string; detail: string; demo: boolean };

export type NodeSummary = {
  node: number;
  name: string;
  online: boolean;
  age_s: number | null;
  reports: number;
  latest: Report | null;
  latest_sc1: Report | null;
};

export type Settings = {
  risk_alert: number;
  rain_alert_mm_h: number;
  low_batt_pct: number;
  guard_armed: boolean;
  energy_saver: boolean;
  storm_watch: boolean;
};

export type EventItem = {
  kind: "saw" | "tilt" | "borer" | "rain" | "bird" | "buzz" | "security";
  title: string;
  detail: string;
  node: number;
  name: string;
  ts: number;
  demo: boolean;
};

/* NEXT_PUBLIC_API: the backend URL. Set it to "same-origin" when the dashboard and
 * API sit behind one HTTPS reverse proxy (Dashboard/Caddyfile). */
const RAW_API = process.env.NEXT_PUBLIC_API ?? "http://localhost:8000";
export const API = RAW_API === "same-origin" ? "" : RAW_API.replace(/\/$/, "");

export function wsURL(token: string) {
  const base = API || (typeof window !== "undefined" ? window.location.origin : "");
  return base.replace(/^http/, "ws") + "/ws" + (token ? `?token=${encodeURIComponent(token)}` : "");
}

/* Login token (only used when the server sets DASH_PASSWORD). */
const TOKEN_KEY = "sylvaecho.token";
export const getToken = () => (typeof window === "undefined" ? "" : localStorage.getItem(TOKEN_KEY) ?? "");
export const setToken = (t: string) => (t ? localStorage.setItem(TOKEN_KEY, t) : localStorage.removeItem(TOKEN_KEY));

export class AuthError extends Error {}

function headers(json = false): HeadersInit {
  const h: Record<string, string> = {};
  if (json) h["content-type"] = "application/json";
  const t = getToken();
  if (t) h.Authorization = `Bearer ${t}`;
  return h;
}

export async function getJSON<T>(path: string): Promise<T> {
  const r = await fetch(`${API}${path}`, { cache: "no-store", headers: headers() });
  if (r.status === 401) throw new AuthError("login required");
  if (!r.ok) throw new Error(`${path}: ${r.status}`);
  return r.json();
}

export async function putSettings(patch: Partial<Settings>): Promise<Settings> {
  const r = await fetch(`${API}/api/settings`, { method: "PUT", headers: headers(true), body: JSON.stringify(patch) });
  if (r.status === 401) throw new AuthError("login required");
  if (!r.ok) throw new Error(`settings: ${r.status}`);
  return r.json();
}

export async function getSession(): Promise<{ auth_required: boolean; ok: boolean }> {
  const r = await fetch(`${API}/api/session`, { cache: "no-store", headers: headers() });
  if (!r.ok) throw new Error(`session: ${r.status}`);
  return r.json();
}

export async function login(password: string): Promise<boolean> {
  const r = await fetch(`${API}/api/login`, { method: "POST", headers: headers(true), body: JSON.stringify({ password }) });
  if (!r.ok) return false;
  setToken((await r.json()).token);
  return true;
}

export async function logout() {
  await fetch(`${API}/api/logout`, { method: "POST", headers: headers() }).catch(() => undefined);
  setToken("");
}

export const clamp = (v: number, a: number, b: number) => Math.min(b, Math.max(a, v));

export function hhmm(d: Date, seconds = false) {
  const p = (n: number) => String(n).padStart(2, "0");
  return `${p(d.getHours())}:${p(d.getMinutes())}${seconds ? ":" + p(d.getSeconds()) : ""}`;
}

/** Hour of day (0-24) for a timestamp. In demo mode a day lasts `dayS` seconds. */
export function hourOf(ts: number, dayS: number) {
  if (dayS >= 86400) {
    const d = new Date(ts * 1000);
    return d.getHours() + d.getMinutes() / 60;
  }
  return ((ts % dayS) / dayS) * 24;
}

export function hourLabel(h: number) {
  const hh = Math.floor(h) % 24;
  const mm = Math.floor((h - Math.floor(h)) * 60);
  return `${String(hh).padStart(2, "0")}:${String(mm).padStart(2, "0")}`;
}

/** 0 at noon, 1 in deep night: drives the forest dimming. */
export function nightness(h: number) {
  const sun = Math.sin(((h - 6) / 12) * Math.PI); // >0 between 06:00 and 18:00
  return clamp(0.5 - sun * 0.9, 0, 1);
}

export function ago(s: number | null) {
  if (s == null) return "never";
  if (s < 60) return `${Math.round(s)} s ago`;
  if (s < 3600) return `${Math.round(s / 60)} min ago`;
  if (s < 86400) return `${Math.round(s / 3600)} h ago`;
  return `${Math.round(s / 86400)} d ago`;
}

/** Nearest report at or before `ts` (reports sorted by ts). */
export function sampleAt(reports: Report[], ts: number): Report | null {
  let best: Report | null = null;
  for (const r of reports) {
    if (r.ts <= ts) best = r;
    else break;
  }
  return best ?? reports[0] ?? null;
}
