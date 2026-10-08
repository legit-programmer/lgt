import * as Dialog from "@radix-ui/react-dialog";
import { Check, Folder } from "lucide-react";
import { useEffect, useState, type FormEvent } from "react";
import { api } from "../../api/client";
import { AgentAvatar } from "../../components/Avatar";
import { activeAgents, hueStyle } from "../../lib/agents";
import { pickFolder } from "../../lib/folder";
import { useUi } from "../../store/ui";
import { reportError, useWorkspace } from "../../store/workspace";

export function NewChannelDialog() {
  const open = useUi((s) => s.newChannelOpen);
  const setOpen = useUi((s) => s.setNewChannelOpen);
  const openChannel = useUi((s) => s.openChannel);
  const agentsById = useWorkspace((s) => s.agents);
  const agents = activeAgents(agentsById);
  const [name, setName] = useState("");
  const [selected, setSelected] = useState<string[]>([]);
  const [cwd, setCwd] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!open) return;
    setName("");
    setSelected([]);
    setCwd(null);
  }, [open]);

  const toggle = (agentId: string) =>
    setSelected((current) => (current.includes(agentId) ? current.filter((id) => id !== agentId) : [...current, agentId]));

  const browse = async () => {
    const picked = await pickFolder("Working directory for the new channel", cwd);
    if (picked) setCwd(picked);
  };

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    const trimmed = name.trim().replace(/^#/, "");
    if (!trimmed) return;
    setSaving(true);
    try {
      const channel = await api.createChannel({ name: trimmed, kind: "channel", agent_ids: selected, cwd });
      setOpen(false);
      await useWorkspace.getState().refreshSummaries();
      openChannel(channel.channel_id);
    } catch (error) {
      reportError(error);
    } finally {
      setSaving(false);
    }
  };

  return (
    <Dialog.Root open={open} onOpenChange={setOpen}>
      <Dialog.Portal>
        <Dialog.Overlay className="fv-dialog-overlay" />
        <Dialog.Content className="fv-dialog fv-glass">
          <Dialog.Title className="fv-dialog-title">New channel</Dialog.Title>
          <Dialog.Description className="fv-dialog-desc">
            Put several agents in a channel to hand work between them.
          </Dialog.Description>
          <form onSubmit={submit} className="new-channel-form">
            <div className="fv-field">
              <label htmlFor="channel-name">Name</label>
              <input id="channel-name" className="fv-input" placeholder="e.g. design-review" value={name}
                autoFocus onChange={(e) => setName(e.target.value)} />
            </div>
            <div className="fv-field">
              <span className="fv-field-label">Agents</span>
              {agents.length ? (
                <div className="pick-list" role="group" aria-label="Agents">
                  {agents.map((agent) => {
                    const checked = selected.includes(agent.agent_id);
                    return (
                      <button type="button" key={agent.agent_id} className="pick-row" aria-pressed={checked} onClick={() => toggle(agent.agent_id)}>
                        <span className="fv-check" data-checked={checked}>{checked ? <Check size={12} strokeWidth={3} /> : null}</span>
                        <AgentAvatar agent={agent} />
                        <span className="fv-name" style={hueStyle(agent)}>{agent.handle}</span>
                        <span className="fv-meta pick-row-detail">{agent.description}</span>
                      </button>
                    );
                  })}
                </div>
              ) : (
                <span className="fv-hint">Create an agent first, or add agents to the channel later.</span>
              )}
            </div>
            <div className="fv-field">
              <span className="fv-field-label">Working directory</span>
              <div className="path-row">
                <input className="fv-input fv-input--mono" placeholder="A managed directory is created for you"
                  value={cwd ?? ""} onChange={(e) => setCwd(e.target.value.trim() ? e.target.value : null)} />
                <button type="button" className="fv-btn" onClick={browse}><Folder /> Browse…</button>
              </div>
              <span className="fv-hint">Every agent in the channel starts here. Leave it empty for a managed directory.</span>
            </div>
            <div className="fv-dialog-actions">
              <Dialog.Close asChild><button type="button" className="fv-btn fv-btn--ghost">Cancel</button></Dialog.Close>
              <button type="submit" className="fv-btn fv-btn--primary" disabled={saving || !name.trim()}>Create channel</button>
            </div>
          </form>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
