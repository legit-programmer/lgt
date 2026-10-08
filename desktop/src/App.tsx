import { useCallback, useEffect, useState } from "react";
import { RotateCcw, Unplug } from "lucide-react";
import { backendUrl, resolveBackendUrl } from "./api/client";
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

type Boot = "resolving" | "loading" | "ready" | "failed";

export function App() {
  const [boot, setBoot] = useState<Boot>("resolving");
  const bootError = useWorkspace((s) => s.bootError);

  const start = useCallback(async () => {
    setBoot("loading");
    try {
      await resolveBackendUrl();
      await useWorkspace.getState().boot();
      workspaceSocket.start();
      setBoot("ready");
    } catch {
      setBoot("failed");
    }
  }, []);

  useEffect(() => {
    void start();
    return () => workspaceSocket.stop();
  }, [start]);

  if (boot === "failed") return <Unreachable message={bootError} onRetry={start} />;
  if (boot !== "ready") return <div className="app-splash fv-backdrop" aria-busy="true" />;
  return <Workspace />;
}

function Workspace() {
  const view = useUi((s) => s.view);
  const navigate = useUi((s) => s.navigate);
  const openChannel = useUi((s) => s.openChannel);
  const setPaletteOpen = useUi((s) => s.setPaletteOpen);
  const agents = useWorkspace((s) => s.agents);
  const channels = useWorkspace((s) => s.channels);
  const hasAgents = activeAgents(agents).length > 0;

  // Land on the most recent conversation, or onboarding with no agents.
  useEffect(() => {
    if (view.kind !== "home") return;
    if (!hasAgents) {
      navigate({ kind: "onboarding" });
      return;
    }
    const recent = Object.values(channels)
      .filter((c) => !c.archived_at)
      .sort((a, b) => b.last_activity_at.localeCompare(a.last_activity_at))[0];
    if (recent) openChannel(recent.channel_id);
  }, [view.kind, hasAgents, channels, navigate, openChannel]);

  // A missing or archived conversation (deep link, or archived elsewhere) falls back home.
  useEffect(() => {
    if (view.kind !== "channel") return;
    const channel = channels[view.channelId];
    if (!channel || channel.archived_at) navigate({ kind: "home" });
  }, [view, channels, navigate]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setPaletteOpen(true);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [setPaletteOpen]);

  return (
    <div className="app fv-backdrop">
      <Sidebar />
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

function Unreachable({ message, onRetry }: { message: string | null; onRetry: () => void }) {
  let url = "";
  try {
    url = backendUrl();
  } catch {
    url = "";
  }
  return (
    <div className="app-splash fv-backdrop">
      <div className="unreachable fv-glass">
        <Unplug className="unreachable-icon" />
        <h1 className="fv-dialog-title">Lgt can't reach its backend</h1>
        <p className="fv-dialog-desc">
          {message ?? "The backend did not answer."} Start it, then retry.
        </p>
        <pre className="unreachable-cmd">uv run python -m lgt --config config.local.json</pre>
        <p className="fv-hint">
          Looking for it at <span className="fv-mono">{url || "the configured URL"}</span>. Set{" "}
          <span className="fv-mono">LGT_BACKEND_URL</span> to use another address, and add this window's origin to{" "}
          <span className="fv-mono">settings.allowed_origins</span>.
        </p>
        <div className="fv-dialog-actions">
          <button className="fv-btn fv-btn--primary" onClick={onRetry}>
            <RotateCcw /> Retry
          </button>
        </div>
      </div>
    </div>
  );
}
