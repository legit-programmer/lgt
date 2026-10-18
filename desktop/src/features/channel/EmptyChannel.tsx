import { Folder, UserPlus } from "lucide-react";
import { api } from "../../api/client";
import type { Agent, ChannelSummary } from "../../api/types";
import { AgentAvatar } from "../../components/Avatar";
import { pickFolder } from "../../lib/folder";
import { displayPath } from "../../lib/format";
import { hueStyle } from "../../lib/agents";
import { useUi } from "../../store/ui";
import { reportError } from "../../store/workspace";

export function EmptyChannel({ channel, members }: { channel: ChannelSummary; members: Agent[] }) {
  const setDetailOpen = useUi((s) => s.setDetailOpen);
  const setDetailTab = useUi((s) => s.setDetailTab);
  const isDm = channel.kind === "dm";
  const changeCwd = async () => {
    const picked = await pickFolder(`Working directory for #${channel.name}`, channel.cwd);
    if (!picked) return;
    try {
      await api.setCwd(channel.channel_id, picked);
    } catch (error) {
      reportError(error);
    }
  };

  const title = isDm ? `Say hello to ${members[0]?.handle ?? channel.name}` : `#${channel.name} is ready`;
  const primary = members.find((agent) => agent.agent_id === channel.primary_agent_id);
  const description = isDm
    ? `Everything here goes to ${members[0]?.handle ?? "this agent"}. It works in`
    : channel.routing_mode === "unassigned"
      ? "Choose a primary agent to start this conversation. Mention another agent to hand work to them."
      : `Unmentioned messages go to ${primary?.handle ?? "the primary agent"}. Mention another agent to hand work to them. ${members.length === 1 ? "It starts" : "They start"} with an empty context in`;

  return (
    <div className="empty-channel">
      <h2 className="empty-title">{title}</h2>
      <p className="empty-desc">
        {description}{isDm || channel.routing_mode !== "unassigned" ? <> <span className="fv-cli">{displayPath(channel.cwd)}</span>.</> : null}
      </p>
      {members.length ? (
        <div className="empty-roster">
          {members.map((agent) => (
            <div key={agent.agent_id} className="empty-agent">
              <AgentAvatar agent={agent} />
              <span className="fv-name" style={hueStyle(agent)}>{agent.handle}</span>
              <span className="fv-meta">{agent.description}</span>
            </div>
          ))}
        </div>
      ) : (
        <p className="empty-desc">This channel has no agents yet. Add one to start.</p>
      )}
      {!isDm ? (
        <div className="empty-actions">
          <button className="fv-btn" onClick={() => { setDetailOpen(true); setDetailTab("agents"); }}>
            <UserPlus /> Add another agent
          </button>
          <button className="fv-btn" onClick={changeCwd}><Folder /> Change working directory</button>
        </div>
      ) : null}
    </div>
  );
}
