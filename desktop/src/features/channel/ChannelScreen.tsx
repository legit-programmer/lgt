import * as DropdownMenu from "@radix-ui/react-dropdown-menu";
import { useQuery } from "@tanstack/react-query";
import {
  Archive, Folder, FolderCog, Hash, MoreHorizontal, PanelRight, Pencil, RotateCcw, Search, Terminal,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { api } from "../../api/client";
import type { Agent, ChannelSummary } from "../../api/types";
import { AgentAvatar } from "../../components/Avatar";
import { StatusBadge } from "../../components/Status";
import { cliLine, hueStyle } from "../../lib/agents";
import { pickFolder } from "../../lib/folder";
import { displayPath, plural, tokens } from "../../lib/format";
import { useUi } from "../../store/ui";
import { contextKey, reportError, useWorkspace } from "../../store/workspace";
import type { BlockContext } from "./blocks";
import { Composer } from "./Composer";
import { DetailPanel } from "./DetailPanel";
import { EmptyChannel } from "./EmptyChannel";
import { RenameDialog } from "./RenameDialog";
import { Timeline } from "./Timeline";

export function ChannelScreen({ channelId, anchorSeq }: { channelId: string; anchorSeq?: number }) {
  const channel = useWorkspace((s) => s.channels[channelId]);
  const agentsById = useWorkspace((s) => s.agents);
  const runs = useWorkspace((s) => s.runs);
  const me = useWorkspace((s) => s.me);
  const detailOpen = useUi((s) => s.detailOpen);

  useEffect(() => {
    if (anchorSeq === undefined) void useWorkspace.getState().loadTimeline(channelId);
    else void useWorkspace.getState().loadAround(channelId, anchorSeq);
  }, [channelId, anchorSeq]);

  const members = useMemo(
    () => (channel?.members ?? [])
      .filter((m) => m.member_kind === "agent")
      .map((m) => agentsById[m.member_id])
      .filter((agent): agent is Agent => !!agent),
    [channel?.members, agentsById],
  );

  const ctx = useMemo<BlockContext>(() => ({
    channelId,
    agents: agentsById,
    memberIds: new Set(members.map((a) => a.agent_id)),
    handles: new Set(Object.values(agentsById).map((a) => a.handle)),
    displayName: me?.display_name ?? "You",
    runs,
  }), [channelId, agentsById, members, me?.display_name, runs]);

  if (!channel) return null;
  const isDm = channel.kind === "dm";
  const agent = isDm ? members[0] : undefined;

  return (
    <div className="channel-screen">
      <section className="fv-pane-glass conversation" aria-label={isDm ? `Direct messages with ${agent?.handle}` : `#${channel.name}`}>
        {isDm && agent ? <DmHeader channel={channel} agent={agent} /> : <ChannelHeader channel={channel} members={members} />}
        <Timeline
          channelId={channelId}
          ctx={ctx}
          anchorSeq={anchorSeq}
          empty={<EmptyChannel channel={channel} members={members} />}
        />
        <div className="conversation-composer">
          <Composer
            channelId={channelId}
            members={members}
            allowMentions={!isDm}
            placeholder={isDm ? `Message ${agent?.handle ?? channel.name} — / for commands` : `Message #${channel.name} — @ to mention, / for commands`}
          />
        </div>
      </section>
      {!isDm && detailOpen ? <DetailPanel channel={channel} members={members} /> : null}
    </div>
  );
}

function CwdButton({ channel }: { channel: ChannelSummary }) {
  const change = async () => {
    const picked = await pickFolder(`Working directory for ${channel.kind === "dm" ? channel.name : `#${channel.name}`}`, channel.cwd);
    if (!picked) return;
    try {
      await api.setCwd(channel.channel_id, picked);
    } catch (error) {
      reportError(error);
    }
  };
  const managed = async () => {
    try {
      await api.setCwd(channel.channel_id, null);
    } catch (error) {
      reportError(error);
    }
  };
  return (
    <DropdownMenu.Root>
      <DropdownMenu.Trigger asChild>
        <button className="fv-chip fv-chip--mono header-chip" title={channel.cwd}>
          <Folder /> <span className="chip-text">{displayPath(channel.cwd)}</span>
        </button>
      </DropdownMenu.Trigger>
      <DropdownMenu.Portal>
        <DropdownMenu.Content className="fv-menu fv-glass" align="start" sideOffset={6}>
          <DropdownMenu.Label className="fv-menu-label fv-label">Working directory</DropdownMenu.Label>
          <DropdownMenu.Item className="fv-menu-item" onSelect={change}>
            <FolderCog /> Change working directory…
          </DropdownMenu.Item>
          {!channel.cwd_managed ? (
            <DropdownMenu.Item className="fv-menu-item" onSelect={managed}>
              <Folder /> Use a managed directory
            </DropdownMenu.Item>
          ) : null}
        </DropdownMenu.Content>
      </DropdownMenu.Portal>
    </DropdownMenu.Root>
  );
}

function ChannelHeader({ channel, members }: { channel: ChannelSummary; members: Agent[] }) {
  const statuses = useWorkspace((s) => s.statuses);
  const detailOpen = useUi((s) => s.detailOpen);
  const setDetailOpen = useUi((s) => s.setDetailOpen);
  const setPaletteOpen = useUi((s) => s.setPaletteOpen);
  const [renaming, setRenaming] = useState(false);
  const working = new Set(channel.active_runs.filter((r) => r.status !== "queued").map((r) => r.agent_id)).size;
  const idle = members.every((a) => statuses[a.agent_id]?.state !== "working");

  const archive = async () => {
    try {
      await api.archiveChannel(channel.channel_id);
    } catch (error) {
      reportError(error);
    }
  };
  const fresh = async () => {
    try {
      await api.newContext(channel.channel_id);
    } catch (error) {
      reportError(error);
    }
  };

  return (
    <header className="conversation-head">
      <Hash className="conversation-hash" />
      <h1 className="conversation-title">{channel.name}</h1>
      <span className="fv-chip">
        {members.length === 0 ? "no agents" : working ? `${working} of ${members.length} working` : `${plural(members.length, "agent")} · ${idle ? "idle" : "busy"}`}
      </span>
      <CwdButton channel={channel} />
      <span className="conversation-head-spacer" />
      <button className="fv-icon-btn" aria-label="Search" onClick={() => setPaletteOpen(true)}><Search /></button>
      <button className="fv-icon-btn" aria-label="Agents panel" aria-pressed={detailOpen} onClick={() => setDetailOpen(!detailOpen)}>
        <PanelRight />
      </button>
      <DropdownMenu.Root>
        <DropdownMenu.Trigger asChild>
          <button className="fv-icon-btn" aria-label="Channel actions"><MoreHorizontal /></button>
        </DropdownMenu.Trigger>
        <DropdownMenu.Portal>
          <DropdownMenu.Content className="fv-menu fv-glass" align="end" sideOffset={6}>
            <DropdownMenu.Item className="fv-menu-item" onSelect={() => setRenaming(true)}><Pencil /> Rename channel</DropdownMenu.Item>
            <DropdownMenu.Item className="fv-menu-item" onSelect={fresh}><RotateCcw /> Fresh context</DropdownMenu.Item>
            <DropdownMenu.Separator className="fv-menu-sep" />
            <DropdownMenu.Item className="fv-menu-item fv-menu-item--danger" onSelect={archive}><Archive /> Archive channel</DropdownMenu.Item>
          </DropdownMenu.Content>
        </DropdownMenu.Portal>
      </DropdownMenu.Root>
      <RenameDialog channel={channel} open={renaming} onOpenChange={setRenaming} />
    </header>
  );
}

function DmHeader({ channel, agent }: { channel: ChannelSummary; agent: Agent }) {
  const status = useWorkspace((s) => s.statuses[agent.agent_id]);
  const stats = useWorkspace((s) => s.contexts[contextKey(channel.channel_id, agent.agent_id)]);
  const navigate = useUi((s) => s.navigate);
  const view = useUi((s) => s.view);
  const setPaletteOpen = useUi((s) => s.setPaletteOpen);
  const harnesses = useQuery({ queryKey: ["harnesses"], queryFn: api.harnesses });
  const activeHere = channel.active_runs.find((r) => r.agent_id === agent.agent_id && r.status !== "queued");
  const state = status?.state ?? "idle";

  const fresh = async () => {
    try {
      await api.newContext(channel.channel_id);
    } catch (error) {
      reportError(error);
    }
  };

  return (
    <header className="conversation-head conversation-head--dm">
      <AgentAvatar agent={agent} status={state} size="lg" />
      <div className="dm-head-text">
        <div className="dm-head-line">
          <h1 className="fv-name dm-head-name" style={hueStyle(agent)}>{agent.handle}</h1>
          {activeHere ? <StatusBadge state="working" since={activeHere.started_at} /> : <StatusBadge state={state} />}
        </div>
        <div className="dm-head-line">
          <span className="fv-chip fv-chip--mono"><Terminal /> {cliLine(agent, harnesses.data)}</span>
          <CwdButton channel={channel} />
          {stats ? (
            <span className="fv-meta">
              {plural(stats.messages_in_context, "message")} in context
              {stats.context_tokens !== null ? ` · ${tokens(stats.context_tokens)} tokens` : ""}
              {stats.model_context_window ? ` of ${tokens(stats.model_context_window)}` : ""}
            </span>
          ) : null}
        </div>
      </div>
      <span className="conversation-head-spacer" />
      <button className="fv-btn" onClick={fresh}><RotateCcw /> Fresh context</button>
      <button className="fv-icon-btn" aria-label="Search" onClick={() => setPaletteOpen(true)}><Search /></button>
      <button className="fv-icon-btn" aria-label={`Edit ${agent.handle}`}
        onClick={() => navigate({ kind: "agent-edit", agentId: agent.agent_id, returnTo: view })}>
        <Pencil />
      </button>
    </header>
  );
}
