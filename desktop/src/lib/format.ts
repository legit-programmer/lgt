const DAY_MS = 86_400_000;

function toDate(value: string | number | Date): Date {
  return value instanceof Date ? value : new Date(value);
}

/** Sidebar-style recency: now, 3m, 2h, tue, 12 Sep. */
export function relativeTime(value: string | null | undefined, now = Date.now()): string {
  if (!value) return "";
  const date = toDate(value);
  const diff = now - date.getTime();
  if (diff < 60_000) return "now";
  if (diff < 3_600_000) return `${Math.floor(diff / 60_000)}m`;
  const today = new Date(now);
  if (diff < DAY_MS && today.getDate() === date.getDate()) return `${Math.floor(diff / 3_600_000)}h`;
  if (diff < 6 * DAY_MS) return date.toLocaleDateString(undefined, { weekday: "short" }).toLowerCase();
  return date.toLocaleDateString(undefined, { day: "numeric", month: "short" });
}

/** Message header time: 14:21. */
export function clockTime(value: string): string {
  return toDate(value).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit", hour12: false });
}

/** Divider time: today 14:20, yesterday 09:02, 12 Sep 14:20. */
export function dayTime(value: string, now = Date.now()): string {
  const date = toDate(value);
  const today = new Date(now);
  const startOfToday = new Date(today.getFullYear(), today.getMonth(), today.getDate()).getTime();
  const time = clockTime(value);
  if (date.getTime() >= startOfToday) return `today ${time}`;
  if (date.getTime() >= startOfToday - DAY_MS) return `yesterday ${time}`;
  return `${date.toLocaleDateString(undefined, { day: "numeric", month: "short" })} ${time}`;
}

/** Elapsed time for a running clock: 0:07, 1:04, 12:30, 1:02:03. */
export function clock(ms: number): string {
  const total = Math.max(0, Math.floor(ms / 1000));
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const seconds = String(total % 60).padStart(2, "0");
  return hours ? `${hours}:${String(minutes).padStart(2, "0")}:${seconds}` : `${minutes}:${seconds}`;
}

/** A finished duration: 0.1s, 48s, 1m 52s, 2h 4m. */
export function duration(ms: number | null | undefined): string {
  if (ms === null || ms === undefined) return "";
  if (ms < 1000) return `${(Math.max(ms, 0) / 1000).toFixed(1)}s`;
  if (ms < 10_000) return `${(ms / 1000).toFixed(1)}s`;
  const seconds = Math.round(ms / 1000);
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ${seconds % 60}s`;
  return `${Math.floor(minutes / 60)}h ${minutes % 60}m`;
}

/** Token counts: 812, 12.4k, 1.2M. */
export function tokens(value: number | null | undefined): string {
  if (value === null || value === undefined) return "–";
  if (value < 1000) return String(value);
  if (value < 1_000_000) return `${(value / 1000).toFixed(value < 10_000 ? 1 : 0).replace(/\.0$/, "")}k`;
  return `${(value / 1_000_000).toFixed(1).replace(/\.0$/, "")}M`;
}

/** File sizes: 812 B, 9.4 KB, 3.1 MB. */
export function bytes(value: number | null | undefined): string {
  if (value === null || value === undefined) return "";
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${(value / 1024 / 1024).toFixed(1)} MB`;
}

export function plural(count: number, one: string, many = `${one}s`): string {
  return `${count} ${count === 1 ? one : many}`;
}

/** Shorten a path for chips: C:\Users\me\code\lgt -> ~\code\lgt when under home. */
export function shortPath(path: string): string {
  const normalized = path.replace(/\//g, "\\");
  const home = normalized.match(/^[A-Za-z]:\\Users\\[^\\]+/i) ?? normalized.match(/^\\(?:home|Users)\\[^\\]+/);
  if (home && normalized.startsWith(home[0])) {
    const rest = normalized.slice(home[0].length);
    return `~${rest.replace(/\\/g, "/")}` || "~";
  }
  return path;
}
