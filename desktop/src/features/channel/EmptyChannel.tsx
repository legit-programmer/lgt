import { useQuery } from "@tanstack/react-query";
import { Folder, UserPlus } from "lucide-react";
import { api } from "../../api/client";
import type { Agent, ChannelSummary } from "../../api/types";
import { AgentAvatar } from "../../components/Avatar";
import { pickFolder } from "../../lib/folder";
import { shortPath } from "../../lib/format";
import { hueStyle } from "../../lib/agents";
import { useUi } from "../../store/ui";
import { reportError } from "../../store/workspace";

export function EmptyChannel({ channel, members }: { channel: ChannelSummary; members: Agent[] }) {
  const setDetailOpen = useUi((s) => s.setDetailOpen);
  const setDetailTab = useUi((s) => s.setDetailTab);
  const isDm = channel.kind === "dm";
  const roster = members.map((a) => a.agent_id).sort().join(",");
  // Suggestions call the router model, so they are fetched once per roster.
  const suggestions = useQuery({
    queryKey: ["suggestions", channel.channel_id, roster],
    queryFn: () => api.suggestions(channel.channel_id),
    enabled: members.length > 0,
    staleTime: Infinity,
    retry: false,
  });

  const send = async (text: string) => {
    try {
      await api.sendMessage(channel.channel_id, { text });
    } catch (error) {
      reportError(error);
    }
  };

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
  const description = isDm
    ? `Everything here goes to ${members[0]?.handle ?? "this agent"}. It works in`
    : `Messages here go to the best-matching agent, or to whoever you @mention. ${members.length === 1 ? "It starts" : "They start"} with an empty context in`;

  return (
    <div className="empty-channel">
      <h2 className="empty-title">{title}</h2>
      <p className="empty-desc">
        {description} <span className="fv-cli">{shortPath(channel.cwd)}</span>.
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
      {suggestions.data?.length ? (
        <div className="empty-suggestions">
          <span className="fv-label">Try asking</span>
          {suggestions.data.map((prompt) => (
            <button key={prompt} className="empty-suggestion" onClick={() => send(prompt)}>{prompt}</button>
          ))}
        </div>
      ) : suggestions.isLoading && members.length ? (
        <p className="fv-meta">Finding a few things to ask…</p>
      ) : null}
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
