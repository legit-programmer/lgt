import { AgentInference } from "../../components/AgentInference";
import { ProviderLogo } from "../../components/ProviderLogo";
import * as DropdownMenu from "@radix-ui/react-dropdown-menu";
import { useQuery } from "@tanstack/react-query";
import {
  Archive, Check, FileText, Folder, FolderCog, Hash, MoreHorizontal, PanelRight, Pencil, RotateCcw, Search, UserPlus, UserRound,
} from "lucide-react";
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { api } from "../../api/client";
import type { Agent, ChannelSummary } from "../../api/types";
import { AgentAvatar } from "../../components/Avatar";
import { StatusBadge } from "../../components/Status";
import { TopBarSlot } from "../../components/TopBar";
import { cliLine, hueStyle } from "../../lib/agents";
import { pickFolder } from "../../lib/folder";
import { useTouchPanels } from "../../lib/platform";
import { windowGlassAvailable } from "../../lib/windowGlass";
import { displayPath, plural, tokens } from "../../lib/format";
import { useUi } from "../../store/ui";
import { contextKey, reportError, useWorkspace } from "../../store/workspace";
import type { BlockContext } from "./blocks";
import { Composer } from "./Composer";
import { DetailPanel } from "./DetailPanel";
import { EmptyChannel } from "./EmptyChannel";
import { RenameDialog } from "./RenameDialog";
import { Timeline } from "./Timeline";
import type { ReplyDraft } from "./ReplyQuote";

const replyDrafts = new Map<string, ReplyDraft>();

export function ChannelScreen({ channelId, anchorSeq }: { channelId: string; anchorSeq?: number }) {
  const channel = useWorkspace((s) => s.channels[channelId]);
  const agentsById = useWorkspace((s) => s.agents);
  const runs = useWorkspace((s) => s.runs);
  const me = useWorkspace((s) => s.me);
  const detailOpen = useUi((s) => s.detailOpen);
  const detailTab = useUi((s) => s.detailTab);
  const pane = useRef<HTMLElement>(null);
  const composerArea = useRef<HTMLDivElement>(null);
  const [reply, setReply] = useState<ReplyDraft | null>(() => replyDrafts.get(channelId) ?? null);
  const [replyLoading, setReplyLoading] = useState(false);
  const replyRequest = useRef(0);
  useEffect(() => {
    if (reply) replyDrafts.set(channelId, reply);
    else replyDrafts.delete(channelId);
  }, [channelId, reply]);
  useEffect(() => () => { replyRequest.current++; }, []);
  const clearReply = useCallback(() => {
    replyRequest.current++;
    setReply(null);
    setReplyLoading(false);
  }, []);
  const onReply = useCallback(async (seq: number, selection?: string) => {
    const request = ++replyRequest.current;
    setReplyLoading(true);
    try {
      const body = { reply_to_seq: seq, ...(selection !== undefined ? { reply_selection: selection } : {}) };
      const quote = await api.previewReply(channelId, body);
      if (request === replyRequest.current) setReply({ ...body, quote });
    } catch (error) {
      if (request === replyRequest.current) reportError(error);
    } finally {
      if (request === replyRequest.current) setReplyLoading(false);
    }
  }, [channelId]);

  // The composer floats over the timeline as frosted glass; the timeline reserves
  // its live height at the bottom so the newest message is never covered.
  useLayoutEffect(() => {
    const area = composerArea.current;
    const section = pane.current;
    if (!area || !section) return;
    const observer = new ResizeObserver(() => section.style.setProperty("--composer-h", `${area.offsetHeight}px`));
    observer.observe(area);
    return () => observer.disconnect();
  }, [channelId]);

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
    isDm: channel?.kind === "dm",
    cwd: channel?.cwd ?? "",
    agents: agentsById,
    memberIds: new Set(members.map((a) => a.agent_id)),
    handles: new Set(Object.values(agentsById).map((a) => a.handle)),
    displayName: me?.display_name ?? "You",
    runs,
    onReply,
  }), [channelId, channel?.kind, channel?.cwd, agentsById, members, me?.display_name, runs, onReply]);

  if (!channel) return null;
  const isDm = channel.kind === "dm";
  const agent = isDm ? members[0] : undefined;

  return (
    <div className={`channel-screen${detailOpen && detailTab === "artefacts" ? " channel-screen--artefacts" : ""}`}>
      <section ref={pane} className="fv-pane-glass conversation" aria-label={isDm ? `Direct messages with ${agent?.handle}` : `#${channel.name}`}>
        {isDm && agent ? <DmHeader channel={channel} agent={agent} /> : <ChannelHeader channel={channel} members={members} />}
        <Timeline
          channelId={channelId}
          ctx={ctx}
          anchorSeq={anchorSeq}
          empty={<EmptyChannel channel={channel} members={members} />}
        />
        <div ref={composerArea} className="conversation-composer">
          {!isDm && channel.routing_mode === "unassigned" ? (
            <PrimaryRequired channel={channel} members={members} />
          ) : (
            <Composer
              channelId={channelId}
              members={members}
              allowMentions={!isDm}
              skillRevision={`${channel.cwd}:${channel.primary_agent_id}:${members.map((member) => `${member.agent_id}:${member.updated_at}`).join(",")}`}
              reply={reply}
              replyLoading={replyLoading}
              displayName={ctx.displayName}
              onClearReply={clearReply}
              placeholder={isDm ? `Message ${agent?.handle ?? channel.name} — / for commands` : `Message #${channel.name} — @ to mention, / for commands`}
            />
          )}
        </div>
      </section>
      {detailOpen && (!isDm || detailTab === "artefacts") ? <DetailPanel channel={channel} members={members} /> : null}
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
        <button className="topbar-quiet topbar-quiet--mono header-chip" title={channel.cwd}>
          {/* A managed folder's path is an internal id; the full path stays in the tooltip and the panel. */}
          <Folder /> <span className="chip-text">{channel.cwd_managed ? "Managed folder" : displayPath(channel.cwd)}</span>
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
  const frosted = useUi((s) => s.frosted);
  const toggleFrosted = useUi((s) => s.toggleFrosted);
  const touchPanels = useTouchPanels();
  const [renaming, setRenaming] = useState(false);
  const [savingHandoff, setSavingHandoff] = useState(false);
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
  const toggleHandoff = async () => {
    setSavingHandoff(true);
    try {
      await api.setHandoff(channel.channel_id, !channel.allow_handoff);
    } catch (error) {
      reportError(error);
    } finally {
      setSavingHandoff(false);
    }
  };

  return (
    <>
    <TopBarSlot target="title">
      <Hash className="topbar-hash" />
      <h1 className="topbar-heading">{channel.name}</h1>
      <span className="topbar-quiet topbar-passive">
        {members.length === 0 ? "no agents" : working ? `${working} of ${members.length} working` : `${plural(members.length, "agent")} · ${idle ? "idle" : "busy"}`}
      </span>
      <CwdButton channel={channel} />
      <PrimaryAgentControl channel={channel} members={members} />
    </TopBarSlot>
    <TopBarSlot target="actions">
      <ArtefactsButton />
      <button className="fv-icon-btn" aria-label="Search" onClick={() => setPaletteOpen(true)}><Search /></button>
      {/* On touch phones the panel opens by swiping left (lib/gestures.ts). */}
      {touchPanels ? null : (
        <button className="fv-icon-btn" aria-label="Agents panel" aria-pressed={detailOpen} onClick={() => setDetailOpen(!detailOpen)}>
          <PanelRight />
        </button>
      )}
      <DropdownMenu.Root>
        <DropdownMenu.Trigger asChild>
          <button className="fv-icon-btn" aria-label="Channel actions"><MoreHorizontal /></button>
        </DropdownMenu.Trigger>
        <DropdownMenu.Portal>
          <DropdownMenu.Content className="fv-menu fv-glass" align="end" sideOffset={6}>
            <DropdownMenu.Item className="fv-menu-item" onSelect={() => setRenaming(true)}><Pencil /> Rename channel</DropdownMenu.Item>
            <DropdownMenu.Item className="fv-menu-item" onSelect={fresh}><RotateCcw /> Fresh context</DropdownMenu.Item>
            <DropdownMenu.CheckboxItem className="fv-menu-item" checked={channel.allow_handoff}
              disabled={savingHandoff} onCheckedChange={() => void toggleHandoff()}>
              <DropdownMenu.ItemIndicator><Check /></DropdownMenu.ItemIndicator>
              Allow agents to hand off ownership
            </DropdownMenu.CheckboxItem>
            <DropdownMenu.Separator className="fv-menu-sep" />
            {windowGlassAvailable() ? (
              <>
                <DropdownMenu.CheckboxItem className="fv-menu-item" checked={frosted} onCheckedChange={toggleFrosted}>
                  <DropdownMenu.ItemIndicator><Check /></DropdownMenu.ItemIndicator>
                  Frosted window
                </DropdownMenu.CheckboxItem>
                <DropdownMenu.Separator className="fv-menu-sep" />
              </>
            ) : null}
            <DropdownMenu.Item className="fv-menu-item fv-menu-item--danger" onSelect={archive}><Archive /> Archive channel</DropdownMenu.Item>
          </DropdownMenu.Content>
        </DropdownMenu.Portal>
      </DropdownMenu.Root>
    </TopBarSlot>
    <RenameDialog channel={channel} open={renaming} onOpenChange={setRenaming} />
    </>
  );
}

export function PrimaryAgentControl({ channel, members, prominent = false }: {
  channel: ChannelSummary;
  members: Agent[];
  prominent?: boolean;
}) {
  const [saving, setSaving] = useState(false);
  const eligibleMembers = members.filter((agent) => !agent.retired_at);
  const primary = eligibleMembers.find((agent) => agent.agent_id === channel.primary_agent_id);
  const choose = async (agentId: string) => {
    if (agentId === channel.primary_agent_id) return;
    setSaving(true);
    try {
      await api.setPrimary(channel.channel_id, agentId);
    } catch (error) {
      reportError(error);
    } finally {
      setSaving(false);
    }
  };

  return (
    <DropdownMenu.Root>
      <DropdownMenu.Trigger asChild>
        <button className={prominent ? "fv-btn fv-btn--primary" : "topbar-quiet header-chip"}
          disabled={saving || eligibleMembers.length === 0}
          aria-label={primary ? `Primary agent: ${primary.handle}` : "Choose a primary agent"}
          title={eligibleMembers.length ? "Choose which agent leads this channel" : "Add an active agent before choosing a primary"}>
          <UserRound /> <span className={prominent ? undefined : "topbar-label"}>
            {saving ? "Saving…" : primary ? `Primary: ${primary.handle}` : "Choose primary"}
          </span>
        </button>
      </DropdownMenu.Trigger>
      <DropdownMenu.Portal>
        <DropdownMenu.Content className="fv-menu fv-glass" align={prominent ? "center" : "start"} sideOffset={6}>
          <DropdownMenu.Label className="fv-menu-label fv-label">Primary agent</DropdownMenu.Label>
          {eligibleMembers.map((agent) => (
            <DropdownMenu.Item key={agent.agent_id} className="fv-menu-item" onSelect={() => void choose(agent.agent_id)}>
              <AgentAvatar agent={agent} />
              <span>{agent.handle}</span>
              {agent.agent_id === channel.primary_agent_id ? <Check /> : null}
            </DropdownMenu.Item>
          ))}
        </DropdownMenu.Content>
      </DropdownMenu.Portal>
    </DropdownMenu.Root>
  );
}

function PrimaryRequired({ channel, members }: { channel: ChannelSummary; members: Agent[] }) {
  const setDetailOpen = useUi((state) => state.setDetailOpen);
  const setDetailTab = useUi((state) => state.setDetailTab);
  const hasActiveMember = members.some((agent) => !agent.retired_at);
  return (
    <div className="primary-required" role="status">
      <div className="primary-required-copy">
        <UserRound />
        <div>
          <strong>Choose a primary agent to start this conversation.</strong>
          <span className="fv-meta">The primary handles unmentioned messages. Agents can hand work to each other as needed.</span>
        </div>
      </div>
      {hasActiveMember ? <PrimaryAgentControl channel={channel} members={members} prominent /> : (
        <button className="fv-btn fv-btn--primary" onClick={() => { setDetailOpen(true); setDetailTab("agents"); }}>
          <UserPlus /> Add an active agent
        </button>
      )}
    </div>
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
    <>
    <TopBarSlot target="title">
      <AgentInference agent={agent}><AgentAvatar agent={agent} status={state} className="topbar-passive" /></AgentInference>
      <h1 className="fv-name topbar-heading" style={hueStyle(agent)}><AgentInference agent={agent}>{agent.handle}</AgentInference></h1>
      <span className="topbar-passive">
        {activeHere ? <StatusBadge state="working" since={activeHere.started_at} /> : <StatusBadge state={state} />}
      </span>
      <span className="fv-chip fv-chip--mono topbar-passive"><ProviderLogo harness={agent.harness} /> {cliLine(agent, harnesses.data)}</span>
      <CwdButton channel={channel} />
      {stats ? (
        <span className="fv-meta topbar-passive topbar-stats">
          {plural(stats.messages_in_context, "message")} in context
          {stats.context_tokens !== null ? ` · ${tokens(stats.context_tokens)} tokens` : ""}
          {stats.model_context_window ? ` of ${tokens(stats.model_context_window)}` : ""}
        </span>
      ) : null}
    </TopBarSlot>
    <TopBarSlot target="actions">
      <ArtefactsButton />
      <button className="fv-btn fv-btn--sm" aria-label="Fresh context" onClick={fresh}>
        <RotateCcw /> <span className="topbar-label">Fresh context</span>
      </button>
      <button className="fv-icon-btn" aria-label="Search" onClick={() => setPaletteOpen(true)}><Search /></button>
      <button className="fv-icon-btn" aria-label={`Edit ${agent.handle}`}
        onClick={() => navigate({ kind: "agent-edit", agentId: agent.agent_id, returnTo: view })}>
        <Pencil />
      </button>
    </TopBarSlot>
    </>
  );
}

function ArtefactsButton() {
  const open = useUi((s) => s.detailOpen && s.detailTab === "artefacts");
  return <button className="fv-icon-btn" aria-label="Artefacts" aria-pressed={open} onClick={() => {
    useUi.getState().setDetailTab("artefacts");
    useUi.getState().setDetailOpen(!open);
  }}><FileText /></button>;
}
