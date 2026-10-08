import { create } from "zustand";

export type View =
  | { kind: "home" }
  | { kind: "channel"; channelId: string; anchorSeq?: number }
  | { kind: "agent-new"; returnTo?: View }
  | { kind: "agent-edit"; agentId: string; returnTo?: View }
  | { kind: "onboarding" };

export type DetailTab = "agents" | "run";
export type Theme = "dark" | "light";

interface UiState {
  view: View;
  detailOpen: boolean;
  detailTab: DetailTab;
  runFilterAgentId: string | null;
  selectedRunId: string | null;
  paletteOpen: boolean;
  newChannelOpen: boolean;
  theme: Theme;
  sidebarOpen: boolean;
  /** Visited views, for back and forward. */
  history: View[];
  historyIndex: number;
  navigate(view: View, options?: { replace?: boolean }): void;
  openChannel(channelId: string, anchorSeq?: number, options?: { replace?: boolean }): void;
  back(): void;
  forward(): void;
  toggleSidebar(): void;
  setDetailOpen(open: boolean): void;
  showRuns(agentId: string | null, runId?: string | null): void;
  setDetailTab(tab: DetailTab): void;
  selectRun(runId: string | null): void;
  setPaletteOpen(open: boolean): void;
  setNewChannelOpen(open: boolean): void;
  toggleTheme(): void;
}

/** The view as a URL hash, so a window can be reloaded or deep-linked. */
export function viewToHash(view: View): string {
  switch (view.kind) {
    case "channel":
      return `#/c/${view.channelId}`;
    case "agent-new":
      return "#/agents/new";
    case "agent-edit":
      return `#/agents/${view.agentId}`;
    case "onboarding":
      return "#/onboarding";
    default:
      return "";
  }
}

export function viewFromHash(hash: string): View {
  const parts = hash.replace(/^#\/?/, "").split("/").filter(Boolean);
  if (parts[0] === "c" && parts[1]) return { kind: "channel", channelId: decodeURIComponent(parts[1]) };
  if (parts[0] === "agents" && parts[1] === "new") return { kind: "agent-new" };
  if (parts[0] === "agents" && parts[1]) return { kind: "agent-edit", agentId: decodeURIComponent(parts[1]) };
  if (parts[0] === "onboarding") return { kind: "onboarding" };
  return { kind: "home" };
}

function syncHash(view: View) {
  const hash = viewToHash(view);
  if (window.location.hash !== hash) window.history.replaceState(null, "", hash || window.location.pathname);
}

// Theme and sidebar visibility are per-window display preferences, so they live in local storage.
function stored(key: string): string | null {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}

function store(key: string, value: string) {
  try {
    localStorage.setItem(key, value);
  } catch {
    // Storage can be unavailable; the preference still applies for this session.
  }
}

function storedTheme(): Theme {
  return stored("lgt.theme") === "light" ? "light" : "dark";
}

const HISTORY_LIMIT = 50;
const initialView = viewFromHash(window.location.hash);

/** Push a view onto the history, dropping forward entries; repeats of the current view are replaced. */
function pushed(history: View[], index: number, view: View, replace: boolean) {
  const current = history[index];
  if (replace || (current && viewToHash(current) === viewToHash(view))) {
    const next = history.slice();
    next[index] = view;
    return { history: next, historyIndex: index };
  }
  const next = [...history.slice(0, index + 1), view].slice(-HISTORY_LIMIT);
  return { history: next, historyIndex: next.length - 1 };
}

function applyTheme(theme: Theme) {
  document.documentElement.dataset.theme = theme;
  store("lgt.theme", theme);
}

export const useUi = create<UiState>((set, get) => ({
  view: initialView,
  detailOpen: true,
  detailTab: "agents",
  runFilterAgentId: null,
  selectedRunId: null,
  paletteOpen: false,
  newChannelOpen: false,
  theme: storedTheme(),
  sidebarOpen: stored("lgt.sidebar") !== "closed",
  history: [initialView],
  historyIndex: 0,
  navigate(view, options) {
    syncHash(view);
    const { history, historyIndex } = get();
    set({ view, ...pushed(history, historyIndex, view, options?.replace ?? false) });
  },
  openChannel(channelId, anchorSeq, options) {
    const view: View = { kind: "channel", channelId, anchorSeq };
    syncHash(view);
    const { history, historyIndex } = get();
    set({ view, selectedRunId: null, ...pushed(history, historyIndex, view, options?.replace ?? false) });
  },
  back() {
    const { history, historyIndex } = get();
    if (historyIndex <= 0) return;
    const view = history[historyIndex - 1];
    syncHash(view);
    set({ view, historyIndex: historyIndex - 1, selectedRunId: null });
  },
  forward() {
    const { history, historyIndex } = get();
    if (historyIndex >= history.length - 1) return;
    const view = history[historyIndex + 1];
    syncHash(view);
    set({ view, historyIndex: historyIndex + 1, selectedRunId: null });
  },
  toggleSidebar() {
    const sidebarOpen = !get().sidebarOpen;
    store("lgt.sidebar", sidebarOpen ? "open" : "closed");
    set({ sidebarOpen });
  },
  setDetailOpen(detailOpen) {
    set({ detailOpen });
  },
  showRuns(agentId, runId = null) {
    set({ detailOpen: true, detailTab: "run", runFilterAgentId: agentId, selectedRunId: runId });
  },
  setDetailTab(detailTab) {
    set({ detailTab });
  },
  selectRun(selectedRunId) {
    set({ selectedRunId });
  },
  setPaletteOpen(paletteOpen) {
    set({ paletteOpen });
  },
  setNewChannelOpen(newChannelOpen) {
    set({ newChannelOpen });
  },
  toggleTheme() {
    const theme = get().theme === "dark" ? "light" : "dark";
    applyTheme(theme);
    set({ theme });
  },
}));

applyTheme(useUi.getState().theme);
