import { useCallback, useEffect, useLayoutEffect, useState } from "react";
import { Link, RotateCcw, Unplug } from "lucide-react";
import { backendUrl, isTauri, PairingRequiredError, resolveBackendUrl } from "./api/client";
import { useWorkspace } from "./store/workspace";
import { workspaceSocket } from "./store/socket";
import { useUi } from "./store/ui";
import { activeAgents } from "./lib/agents";
import { Sidebar } from "./features/sidebar/Sidebar";
import { ChannelScreen } from "./features/channel/ChannelScreen";
import { AgentForm } from "./features/agents/AgentForm";
import { Onboarding } from "./features/onboarding/Onboarding";
import { CommandPalette } from "./features/palette/CommandPalette";
import { NewChannelDialog } from "./features/channel/NewChannelDialog";
import { Toasts } from "./components/Toasts";
import { TopBar } from "./components/TopBar";
import { StartupOverlay } from "./components/StartupOverlay";
import { ConnectionDialog } from "./features/settings/ConnectionDialog";
import { ScanOverlay } from "./components/ScanOverlay";
import { PathPromptHost } from "./components/PathPrompt";
import { isMobile, useCompactLayout, useTouchPanels } from "./lib/platform";
import { swipeAction, useSwipe } from "./lib/gestures";
import { cancelScan, isScanning } from "./lib/scan";

type Boot = "resolving" | "loading" | "ready" | "failed" | "unpaired";

// React StrictMode mounts effects twice in development. Share the in-flight
// startup so the daemon handshake and workspace boot happen only once.
let startupTask: Promise<void> | null = null;

function startWorkspace(): Promise<void> {
  if (startupTask) return startupTask;
  const task = (async () => {
    await resolveBackendUrl();
    await useWorkspace.getState().boot();
    workspaceSocket.start();
  })();
  startupTask = task;
  void task.then(
    () => { if (startupTask === task) startupTask = null; },
    () => { if (startupTask === task) startupTask = null; },
  );
  return task;
}

function startupErrorText(error: unknown): string {
  if (typeof error === "string") return error;
  if (error instanceof Error && error.message) return error.message;
  return String(error);
}

export function App() {
  const [boot, setBoot] = useState<Boot>("resolving");
  const [startupError, setStartupError] = useState<string | null>(null);
  const bootError = useWorkspace((s) => s.bootError);

  const start = useCallback(async () => {
    setBoot("loading");
    setStartupError(null);
    try {
      await startWorkspace();
      setBoot("ready");
    } catch (error) {
      if (error instanceof PairingRequiredError) {
        setBoot("unpaired");
        return;
      }
      setStartupError(startupErrorText(error));
      setBoot("failed");
    }
  }, []);

  useEffect(() => {
    void start();
    return () => workspaceSocket.stop();
  }, [start]);

  useAndroidBackButton();

  let content;
  if (boot === "unpaired") content = <Unpaired />;
  else if (boot === "failed") content = <Unreachable message={startupError ?? bootError} onRetry={start} />;
  else if (boot !== "ready") content = <StartupOverlay />;
  else content = <Workspace />;
  // The shell carries the backdrop, so the top bar and the UI share one ground.
  return (
    <div className="app-shell fv-backdrop">
      <TopBar workspace={boot === "ready"} />
      {content}
      <ScanOverlay />
      <PathPromptHost />
    </div>
  );
}

/*
 * Android's back gesture closes the innermost layer first: a running scan, an
 * open dialog or menu, the phone drawer or panel. Then it walks the view
 * history, and leaves the app from the first view. Registering the listener
 * replaces the default, which would exit at once because views use replaceState.
 */
function useAndroidBackButton() {
  useEffect(() => {
    if (!isMobile || !isTauri()) return;
    let live = true;
    let unregister: (() => void) | undefined;
    void (async () => {
      const { exit, onBackButtonPress } = await import("@tauri-apps/api/app");
      const listener = await onBackButtonPress(() => {
        if (isScanning()) {
          void cancelScan();
          return;
        }
        if (document.querySelector("[role=dialog][data-state=open], [role=menu][data-state=open]")) {
          // Radix dialogs, popovers, menus and the palette close on Escape.
          document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
          return;
        }
        const ui = useUi.getState();
        if (window.matchMedia("(max-width: 760px)").matches) {
          if (ui.sidebarOpen) return ui.setSidebarOpen(false);
          if (ui.detailOpen && ui.view.kind === "channel") return ui.setDetailOpen(false);
        }
        if (ui.historyIndex > 0) ui.back();
        else void exit(0);
      });
      if (live) unregister = () => void listener.unregister();
      else void listener.unregister();
    })();
    return () => {
      live = false;
      unregister?.();
    };
  }, []);
}

function Workspace() {
  const view = useUi((s) => s.view);
  const navigate = useUi((s) => s.navigate);
  const openChannel = useUi((s) => s.openChannel);
  const setPaletteOpen = useUi((s) => s.setPaletteOpen);
  const sidebarOpen = useUi((s) => s.sidebarOpen);
  const setSidebarOpen = useUi((s) => s.setSidebarOpen);
  const setDetailOpen = useUi((s) => s.setDetailOpen);
  const compact = useCompactLayout();
  const touchPanels = useTouchPanels();
  const agents = useWorkspace((s) => s.agents);
  const channels = useWorkspace((s) => s.channels);
  const hasAgents = activeAgents(agents).length > 0;
  // Channels have the agents/run panel; DMs and the other views don't.
  const hasDetail = view.kind === "channel" && channels[view.channelId]?.kind === "channel";

  useSwipe(touchPanels, (swipe) => {
    const ui = useUi.getState();
    const change = swipeAction(swipe, { sidebarOpen: ui.sidebarOpen, detailOpen: ui.detailOpen, hasDetail });
    if (change && "sidebarOpen" in change) setSidebarOpen(change.sidebarOpen);
    else if (change) setDetailOpen(change.detailOpen);
  });

  // Land on the most recent conversation, or onboarding with no agents.
  useEffect(() => {
    if (view.kind !== "home") return;
    // Redirects replace the history entry, so Back never lands on an empty view.
    if (!hasAgents) {
      navigate({ kind: "onboarding" }, { replace: true });
      return;
    }
    const recent = Object.values(channels)
      .filter((c) => !c.archived_at)
      .sort((a, b) => b.last_activity_at.localeCompare(a.last_activity_at))[0];
    if (recent) openChannel(recent.channel_id, undefined, { replace: true });
  }, [view.kind, hasAgents, channels, navigate, openChannel]);

  // On a phone the sidebar and panel overlay the conversation: each view opens
  // with both closed, so picking a conversation from the drawer reveals it.
  // A layout effect, so a stored open sidebar never flashes over the first view.
  useLayoutEffect(() => {
    if (!compact) return;
    setSidebarOpen(false);
    setDetailOpen(false);
  }, [compact, view, setSidebarOpen, setDetailOpen]);

  // A missing or archived conversation (deep link, or archived elsewhere) falls back home.
  useEffect(() => {
    if (view.kind !== "channel") return;
    const channel = channels[view.channelId];
    if (!channel || channel.archived_at) navigate({ kind: "home" }, { replace: true });
  }, [view, channels, navigate]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setPaletteOpen(true);
      } else if (event.altKey && (event.key === "ArrowLeft" || event.key === "ArrowRight")) {
        event.preventDefault();
        if (event.key === "ArrowLeft") useUi.getState().back();
        else useUi.getState().forward();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [setPaletteOpen]);

  return (
    <div className={`app${sidebarOpen && !compact ? "" : " app--no-sidebar"}`}>
      {sidebarOpen && compact ? <div className="drawer-scrim" aria-hidden="true" onClick={() => setSidebarOpen(false)} /> : null}
      {sidebarOpen ? <Sidebar /> : null}
      <main className="app-main">
        {view.kind === "channel" && channels[view.channelId] ? (
          <ChannelScreen key={view.channelId} channelId={view.channelId} anchorSeq={view.anchorSeq} />
        ) : null}
        {view.kind === "agent-new" ? <AgentForm key="new" agentId={null} /> : null}
        {view.kind === "agent-edit" ? <AgentForm key={view.agentId} agentId={view.agentId} /> : null}
        {view.kind === "onboarding" ? <Onboarding /> : null}
      </main>
      <CommandPalette />
      <NewChannelDialog />
      <Toasts />
    </div>
  );
}

/** First launch on a phone: there is no local workspace, only pairing. */
function Unpaired() {
  const [connectionOpen, setConnectionOpen] = useState(false);
  return (
    <div className="app-splash">
      <div className="unreachable fv-glass">
        <Link className="unreachable-icon" />
        <h1 className="fv-dialog-title">Pair with your workspace</h1>
        <p className="fv-dialog-desc">
          Lgt on your phone connects to the workspace running on your computer.
        </p>
        <p className="fv-hint">
          On that computer, open Settings → Devices and create a connection. Then scan its QR code here.
        </p>
        <div className="fv-dialog-actions">
          <button className="fv-btn fv-btn--primary" onClick={() => setConnectionOpen(true)}>
            <Link /> Connect to a workspace
          </button>
        </div>
        <ConnectionDialog open={connectionOpen} onOpenChange={setConnectionOpen} />
      </div>
    </div>
  );
}

function Unreachable({ message, onRetry }: { message: string | null; onRetry: () => void }) {
  const [connectionOpen, setConnectionOpen] = useState(false);
  const desktop = isTauri();
  let url = "";
  try {
    url = backendUrl();
  } catch {
    url = "";
  }
  return (
    <div className="app-splash">
      <div className="unreachable fv-glass">
        <Unplug className="unreachable-icon" />
        <h1 className="fv-dialog-title">Lgt couldn't open your workspace</h1>
        <p className="fv-dialog-desc">
          {message ?? (isMobile ? "Your workspace did not answer." : "Your local workspace did not answer.")}
        </p>
        {isMobile ? (
          <p className="fv-hint">Check that your phone can reach the workspace computer, then retry.</p>
        ) : desktop ? (
          <p className="fv-hint">Retry to reconnect or start your workspace again.</p>
        ) : <>
        <pre className="unreachable-cmd">uv run python -m lgt --config config.local.json</pre>
        <p className="fv-hint">
          Looking for it at <span className="fv-mono">{url || "the configured URL"}</span>. Set{" "}
          <span className="fv-mono">LGT_BACKEND_URL</span> to use another address, and add this window's origin to{" "}
          <span className="fv-mono">settings.allowed_origins</span>.
        </p>
        </>}
        <div className="fv-dialog-actions">
          <button className="fv-btn fv-btn--primary" onClick={onRetry}>
            <RotateCcw /> Retry
          </button>
          <button className="fv-btn fv-btn--ghost" onClick={() => setConnectionOpen(true)}>Connect to a workspace</button>
        </div>
        <ConnectionDialog open={connectionOpen} onOpenChange={setConnectionOpen} />
      </div>
    </div>
  );
}
