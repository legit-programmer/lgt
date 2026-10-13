import * as Dialog from "@radix-ui/react-dialog";
import { useState } from "react";
import { api } from "../../api/client";
import type { SkillEntry } from "../../api/types";
import { ProviderLogo } from "../../components/ProviderLogo";
import { harnessLabel } from "../../lib/agents";
import { useUi } from "../../store/ui";
import { reportError } from "../../store/workspace";

export function SkillDialog({ skill, channelId, kind, onChoose, onClose, onRefresh }: {
  skill: SkillEntry; channelId: string; kind: "channel" | "dm";
  onChoose: (agentId: string) => void; onClose: () => void; onRefresh: () => Promise<unknown>;
}) {
  const [adding, setAdding] = useState(false);
  const navigate = useUi((state) => state.navigate);
  const returnTo = { kind: "channel" as const, channelId };
  const edit = (agentId: string, harness?: string) => {
    onClose();
    navigate({ kind: "agent-edit", agentId, returnTo, harness });
  };
  const add = async (agentId: string) => {
    setAdding(true);
    try {
      await api.addMember(channelId, agentId);
      await onRefresh();
      onChoose(agentId);
    } catch (error) { reportError(error); }
    finally { setAdding(false); }
  };
  return <Dialog.Root open onOpenChange={(open) => { if (!open) onClose(); }}>
    <Dialog.Portal>
      <Dialog.Overlay className="fv-dialog-overlay" />
      <Dialog.Content className="fv-dialog fv-glass">
        <Dialog.Title className="fv-dialog-title"><ProviderLogo harness={skill.harness} /> /{skill.name}</Dialog.Title>
        <Dialog.Description className="fv-dialog-desc">
          {skill.description}<br />{harnessLabel(skill.harness)} · {skill.plugin_id ?? skill.scope}
        </Dialog.Description>
        <p className="fv-meta">{skill.required_tools === null ? "Permission requirements are unknown. The agent's tool policy applies during execution."
          : `Declared required tools: ${skill.required_tools.join(", ") || "none"}.`}</p>
        {skill.reason ? <p className="fv-error-text">{skill.reason}</p> : null}
        <div className="skill-executors">
          {skill.agents.filter((agent) => agent.in_channel).map((agent) => <div key={agent.agent_id} className="skill-executor">
            <span className="fv-mono">@{agent.handle}</span>
            {agent.eligible ? <button className="fv-btn fv-btn--primary fv-btn--sm" onClick={() => onChoose(agent.agent_id)}>
              Run with {agent.handle}{skill.recommended_agent_id === agent.agent_id ? " · recommended" : ""}
            </button> : <>
              <span className="fv-meta">{agent.reason}</span>
              <button className="fv-btn fv-btn--sm" disabled={!skill.enabled} onClick={() => edit(agent.agent_id)}>
                Change backend or tools
              </button>
              {agent.reason_code === "harness_mismatch" ? <button className="fv-btn fv-btn--sm" disabled={!skill.enabled}
                onClick={() => edit(agent.agent_id, skill.harness)}>Switch to {harnessLabel(skill.harness)}</button> : null}
            </>}
          </div>)}
          {kind === "channel" ? <>
            {skill.agents.filter((agent) => !agent.in_channel && agent.eligible).map((agent) =>
              <button key={agent.agent_id} className="fv-btn fv-btn--sm" disabled={adding} onClick={() => void add(agent.agent_id)}>
                Add {agent.handle} to channel
              </button>)}
            <button className="fv-btn fv-btn--sm" disabled={!skill.enabled} onClick={() => {
              onClose(); navigate({ kind: "agent-new", returnTo, harness: skill.harness, addToChannelId: channelId });
            }}>Create a {harnessLabel(skill.harness)} agent</button>
          </> : null}
        </div>
        <div className="fv-dialog-actions"><Dialog.Close asChild><button className="fv-btn fv-btn--ghost">Close</button></Dialog.Close></div>
      </Dialog.Content>
    </Dialog.Portal>
  </Dialog.Root>;
}
