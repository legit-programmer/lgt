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
  navigate(view: View): void;
  openChannel(channelId: string, anchorSeq?: number): void;
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

// Theme is a per-window display preference, so it lives in local storage.
function storedTheme(): Theme {
  try {
    return localStorage.getItem("lgt.theme") === "light" ? "light" : "dark";
  } catch {
    return "dark";
  }
}

function applyTheme(theme: Theme) {
  document.documentElement.dataset.theme = theme;
  try {
    localStorage.setItem("lgt.theme", theme);
  } catch {
    // Storage can be unavailable; the theme still applies for this session.
  }
}

export const useUi = create<UiState>((set, get) => ({
  view: viewFromHash(window.location.hash),
  detailOpen: true,
  detailTab: "agents",
  runFilterAgentId: null,
  selectedRunId: null,
  paletteOpen: false,
  newChannelOpen: false,
  theme: storedTheme(),
  navigate(view) {
    syncHash(view);
    set({ view });
  },
  openChannel(channelId, anchorSeq) {
    const view: View = { kind: "channel", channelId, anchorSeq };
    syncHash(view);
    set({ view, selectedRunId: null });
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
