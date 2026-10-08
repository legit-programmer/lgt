import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Folder, RefreshCw } from "lucide-react";
import { useEffect, useState } from "react";
import { api } from "../../api/client";
import type { Harness, Template } from "../../api/types";
import { AgentAvatar } from "../../components/Avatar";
import { harnessLabel, hueStyle } from "../../lib/agents";
import { pickFolder } from "../../lib/folder";
import { useUi } from "../../store/ui";
import { reportError, useWorkspace } from "../../store/workspace";

export function Onboarding() {
  const queryClient = useQueryClient();
  const navigate = useUi((s) => s.navigate);
  const openChannel = useUi((s) => s.openChannel);
  const harnesses = useQuery({ queryKey: ["harnesses"], queryFn: api.harnesses });
  const templates = useQuery({ queryKey: ["templates", harnesses.dataUpdatedAt], queryFn: api.templates });
  const [selected, setSelected] = useState<string[] | null>(null);
  const [cwd, setCwd] = useState("");
  const [scanning, setScanning] = useState(false);
  const [creating, setCreating] = useState(false);

  // Preselect the first two starters once they load.
  useEffect(() => {
    if (selected === null && templates.data) setSelected(templates.data.slice(0, 2).map((t) => t.id));
  }, [templates.data, selected]);

  const chosen = selected ?? [];
  const toggle = (id: string) => setSelected(chosen.includes(id) ? chosen.filter((t) => t !== id) : [...chosen, id]);

  const scan = async () => {
    setScanning(true);
    try {
      queryClient.setQueryData(["harnesses"], await api.scanHarnesses());
      await templates.refetch();
    } catch (error) {
      reportError(error);
    } finally {
      setScanning(false);
    }
  };

  const browse = async () => {
    const picked = await pickFolder("Where should your agents work?", cwd || null);
    if (picked) setCwd(picked);
  };

  const create = async () => {
    if (!chosen.length || !cwd.trim()) return;
    setCreating(true);
    try {
      const result = await api.bootstrap(chosen, cwd.trim());
      for (const agent of result.agents) useWorkspace.getState().upsertAgent(agent);
      await useWorkspace.getState().refreshSummaries();
      openChannel(result.channel.channel_id);
    } catch (error) {
      reportError(error);
    } finally {
      setCreating(false);
    }
  };

  const clis = (harnesses.data ?? []).filter((h) => h.harness !== "custom");

  return (
    <div className="onboarding fv-pane-glass">
      <div className="onboarding-inner">
        <span className="fv-label">No agents yet</span>
        <h1 className="onboarding-title">Set up your first agents</h1>
        <p className="onboarding-desc">
          Each agent is a specialist backed by a coding CLI on this machine. Pick a few to start with — you can change everything later.
        </p>

        <ol className="onboarding-steps">
          <li className="onboarding-step">
            <div className="step-head">
              <span className="step-number">1</span>
              <h2 className="step-title">CLIs found on this machine</h2>
              <button className="fv-btn fv-btn--sm" onClick={scan} disabled={scanning}><RefreshCw /> Scan again</button>
            </div>
            <div className="fv-card cli-list">
              {clis.map((harness) => <CliRow key={harness.harness} harness={harness} />)}
              {harnesses.isLoading ? <p className="fv-meta cli-list-empty">Scanning…</p> : null}
            </div>
          </li>

          <li className="onboarding-step">
            <div className="step-head">
              <span className="step-number">2</span>
              <h2 className="step-title">Choose starter agents</h2>
              <span className="fv-meta">{chosen.length} selected</span>
            </div>
            {templates.data?.length === 0 ? (
              <p className="fv-hint">No starters match the CLIs on this machine. Install one, scan again, or start from scratch.</p>
            ) : null}
            <div className="template-grid">
              {templates.data?.map((template, index) => (
                <TemplateCard key={template.id} template={template} hue={index} selected={chosen.includes(template.id)}
                  onToggle={() => toggle(template.id)} />
              ))}
            </div>
          </li>

          <li className="onboarding-step">
            <div className="step-head">
              <span className="step-number">3</span>
              <h2 className="step-title">Where should they work?</h2>
            </div>
            <div className="path-row">
              <input className="fv-input fv-input--mono" placeholder="C:\Users\you\code\project" value={cwd}
                aria-label="Working directory" onChange={(e) => setCwd(e.target.value)} />
              <button className="fv-btn" onClick={browse}><Folder /> Browse…</button>
            </div>
            <span className="fv-hint">Starter agents use this folder by default. We'll also create a #general channel with them in it.</span>
          </li>
        </ol>

        <div className="onboarding-actions">
          <button className="fv-btn fv-btn--primary" onClick={create} disabled={creating || !chosen.length || !cwd.trim()}>
            {creating ? "Creating…" : `Create ${chosen.length} ${chosen.length === 1 ? "agent" : "agents"}`}
          </button>
          <button className="fv-btn fv-btn--ghost" onClick={() => navigate({ kind: "agent-new", returnTo: { kind: "onboarding" } })}>
            Start from scratch instead
          </button>
        </div>
      </div>
    </div>
  );
}

function CliRow({ harness }: { harness: Harness }) {
  const ready = harness.found && harness.auth !== "signed_out";
  const auth = harness.auth === "signed_in" ? "signed in" : harness.auth === "signed_out" ? "signed out" : null;
  const detail = harness.found
    ? [harness.path, harness.version, auth].filter(Boolean).join(" · ")
    : "not found · install it, then scan again";
  return (
    <div className="cli-row">
      <span className="cli-name">{harnessLabel(harness.harness)}</span>
      <span className="cli-detail">{detail}</span>
      <span className={`fv-chip ${ready ? "fv-chip--success" : "fv-chip--failed"}`}>
        {!harness.found ? "missing" : harness.auth === "signed_out" ? "sign in" : "ready"}
      </span>
    </div>
  );
}

function TemplateCard({ template, hue, selected, onToggle }: { template: Template; hue: number; selected: boolean; onToggle: () => void }) {
  const agent = { name: template.name, hue, avatar: { style: "bottts", seed: template.id } };
  return (
    <button className={`fv-card template-card${selected ? " is-selected" : ""}`} aria-pressed={selected} onClick={onToggle}>
      <span className="template-top">
        <AgentAvatar agent={agent} />
        <span className="template-name-block">
          <span className="fv-name" style={hueStyle(agent)}>{template.id}</span>
          <span className="fv-meta fv-mono">{harnessLabel(template.harness)} · {template.model}</span>
        </span>
        <span className="fv-check" data-checked={selected}>{selected ? <Check size={12} strokeWidth={3} /> : null}</span>
      </span>
      <span className="template-desc">{template.description}</span>
      {template.allowed_tools.length ? <span className="fv-meta fv-mono">{template.allowed_tools.join(" · ")}</span> : null}
    </button>
  );
}
