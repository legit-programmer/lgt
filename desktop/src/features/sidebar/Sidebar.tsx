import * as DropdownMenu from "@radix-ui/react-dropdown-menu";
import { useState, type ReactNode } from "react";
import { Bot, Hash, Moon, Plus, Search, SquarePen, Sun } from "lucide-react";
import type { Agent, AgentStatus, ChannelSummary } from "../../api/types";
import { AgentAvatar, PersonAvatar } from "../../components/Avatar";
import { activeAgents } from "../../lib/agents";
import { relativeTime } from "../../lib/format";
import { useNow } from "../../lib/useNow";
import { useUi } from "../../store/ui";
import { useWorkspace } from "../../store/workspace";
import { ProfileDialog } from "./ProfileDialog";

export function Sidebar() {
  const agentsById = useWorkspace((s) => s.agents);
  const channels = useWorkspace((s) => s.channels);
  const statuses = useWorkspace((s) => s.statuses);
  const me = useWorkspace((s) => s.me);
  const view = useUi((s) => s.view);
  const openChannel = useUi((s) => s.openChannel);
  const navigate = useUi((s) => s.navigate);
  const setPaletteOpen = useUi((s) => s.setPaletteOpen);
  const setNewChannelOpen = useUi((s) => s.setNewChannelOpen);
  const theme = useUi((s) => s.theme);
  const toggleTheme = useUi((s) => s.toggleTheme);
  const now = useNow(30_000);
  const [editingProfile, setEditingProfile] = useState(false);

  const agents = activeAgents(agentsById);
  const activeId = view.kind === "channel" ? view.channelId : null;
  const dms = agents
    .map((agent) => ({ agent, channel: agent.dm_channel_id ? channels[agent.dm_channel_id] : undefined }))
    .filter((row): row is { agent: Agent; channel: ChannelSummary } => !!row.channel && !row.channel.archived_at);
  const rooms = Object.values(channels)
    .filter((c) => c.kind === "channel" && !c.archived_at)
    .sort((a, b) => b.last_activity_at.localeCompare(a.last_activity_at));
  const working = agents.filter((a) => statuses[a.agent_id]?.state === "working").length;
  const displayName = me?.display_name ?? "You";

  return (
    <aside className="sidebar" aria-label="Conversations">
      <div className="sidebar-head">
        <span className="sidebar-brand">Lgt</span>
        <DropdownMenu.Root>
          <DropdownMenu.Trigger asChild>
            <button className="fv-icon-btn" aria-label="New conversation or agent">
              <SquarePen />
            </button>
          </DropdownMenu.Trigger>
          <DropdownMenu.Portal>
            <DropdownMenu.Content className="fv-menu fv-glass" align="end" sideOffset={6}>
              <DropdownMenu.Item className="fv-menu-item" onSelect={() => setNewChannelOpen(true)}>
                <Hash /> New channel
              </DropdownMenu.Item>
              <DropdownMenu.Item className="fv-menu-item" onSelect={() => navigate({ kind: "agent-new", returnTo: view })}>
                <Bot /> New agent
              </DropdownMenu.Item>
            </DropdownMenu.Content>
          </DropdownMenu.Portal>
        </DropdownMenu.Root>
      </div>

      <button className="sidebar-search" onClick={() => setPaletteOpen(true)}>
        <Search />
        <span>Search or jump to…</span>
        <kbd className="fv-kbd">Ctrl K</kbd>
      </button>

      <nav className="sidebar-scroll">
        <SectionHeader label="Direct messages" count={dms.length}
          action={{ label: "New agent", onClick: () => navigate({ kind: "agent-new", returnTo: view }) }} />
        {dms.length === 0 ? (
          <p className="sidebar-empty">Your agents show up here. Each one gets its own private conversation.</p>
        ) : (
          dms.map(({ agent, channel }) => (
            <DmRow key={agent.agent_id} agent={agent} channel={channel} status={statuses[agent.agent_id]}
              active={activeId === channel.channel_id} now={now} onOpen={() => openChannel(channel.channel_id)} />
          ))
        )}

        <SectionHeader label="Channels" count={rooms.length}
          action={{ label: "New channel", onClick: () => setNewChannelOpen(true) }} />
        {rooms.length === 0 ? (
          <p className="sidebar-empty">Put several agents in a channel to hand work between them.</p>
        ) : (
          rooms.map((channel) => (
            <ChannelRow key={channel.channel_id} channel={channel} agents={agentsById}
              active={activeId === channel.channel_id} now={now} onOpen={() => openChannel(channel.channel_id)} />
          ))
        )}
      </nav>

      <div className="sidebar-foot">
        <button className="sidebar-foot-profile" onClick={() => setEditingProfile(true)} aria-label="Edit your display name">
          <PersonAvatar name={displayName} size="lg" />
          <span className="sidebar-foot-text">
            <span className="sidebar-foot-name">{displayName}</span>
            <span className="fv-label">
              {agents.length} {agents.length === 1 ? "agent" : "agents"} · {working} working
            </span>
          </span>
        </button>
        <ProfileDialog open={editingProfile} onOpenChange={setEditingProfile} />
        <button className="fv-icon-btn" onClick={toggleTheme}
          aria-label={theme === "dark" ? "Switch to light theme" : "Switch to dark theme"}>
          {theme === "dark" ? <Sun /> : <Moon />}
        </button>
      </div>
    </aside>
  );
}

function SectionHeader({ label, count, action }: { label: string; count: number; action: { label: string; onClick: () => void } }) {
  return (
    <div className="sidebar-section">
      <span className="fv-label">{label}</span>
      <span className="sidebar-section-end">
        <button className="fv-icon-btn fv-icon-btn--sm sidebar-section-add" aria-label={action.label} onClick={action.onClick}>
          <Plus />
        </button>
        <span className="fv-meta">{count}</span>
      </span>
    </div>
  );
}

interface DmRowProps {
  agent: Agent;
  channel: ChannelSummary;
  status: AgentStatus | undefined;
  active: boolean;
  now: number;
  onOpen: () => void;
}

function DmRow({ agent, channel, status, active, now, onOpen }: DmRowProps) {
  const state = status?.state ?? "idle";
  let line: ReactNode = channel.preview?.text_excerpt ?? agent.description;
  let failed = false;
  if (state === "working" && status?.activity) {
    line = `${status.activity.summary}…`;
  } else if (state === "failed" && status?.last_failure) {
    const error = status.last_failure.error;
    line = error?.exit_code !== null && error?.exit_code !== undefined
      ? `Run failed · exit ${error.exit_code}`
      : `Run failed · ${error?.code ?? "error"}`;
    failed = true;
  }
  return (
    <button className={`sidebar-row${active ? " is-active" : ""}`} onClick={onOpen} aria-current={active ? "page" : undefined}>
      <AgentAvatar agent={agent} status={state} />
      <span className="sidebar-row-text">
        <span className="sidebar-row-top">
          <span className="fv-name sidebar-row-name" style={{ color: "var(--text-1)" }}>{agent.handle}</span>
          <span className="fv-meta">{relativeTime(channel.last_activity_at, now)}</span>
          {channel.unread_count > 0 ? <span className="unread-dot" aria-label={`${channel.unread_count} unread`} /> : null}
        </span>
        <span className={`sidebar-row-line${failed ? " is-failed" : ""}`}>{line}</span>
      </span>
    </button>
  );
}

interface ChannelRowProps {
  channel: ChannelSummary;
  agents: Record<string, Agent>;
  active: boolean;
  now: number;
  onOpen: () => void;
}

function ChannelRow({ channel, agents, active, now, onOpen }: ChannelRowProps) {
  const workingIds = [...new Set(channel.active_runs.filter((r) => r.status !== "queued").map((r) => r.agent_id))];
  let line: string;
  if (workingIds.length) {
    line = `${workingIds.length} working · ${workingIds.map((id) => agents[id]?.handle ?? "agent").join(", ")}`;
  } else if (channel.preview) {
    const author = channel.preview.author_id === "local" ? "you" : agents[channel.preview.author_id]?.handle;
    line = author ? `${author}: ${channel.preview.text_excerpt}` : channel.preview.text_excerpt;
  } else {
    line = "No messages yet";
  }
  const fresh = !channel.preview && now - new Date(channel.created_at).getTime() < 3_600_000;
  return (
    <button className={`sidebar-row${active ? " is-active" : ""}`} onClick={onOpen} aria-current={active ? "page" : undefined}>
      <span className="channel-tile" aria-hidden="true"><Hash /></span>
      <span className="sidebar-row-text">
        <span className="sidebar-row-top">
          <span className="sidebar-row-name channel-name">{channel.name}</span>
          <span className="fv-meta">{fresh ? "new" : relativeTime(channel.last_activity_at, now)}</span>
          {channel.unread_count > 0 ? <span className="unread-dot" aria-label={`${channel.unread_count} unread`} /> : null}
        </span>
        <span className="sidebar-row-line">{line}</span>
      </span>
    </button>
  );
}
