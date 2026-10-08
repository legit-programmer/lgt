import * as Dialog from "@radix-ui/react-dialog";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, ChevronLeft, Folder, RefreshCw, Terminal } from "lucide-react";
import { useEffect, useMemo, useState, type FormEvent } from "react";
import { api, ApiError } from "../../api/client";
import type { Agent, AgentInput, Avatar, Harness } from "../../api/types";
import { AgentAvatar } from "../../components/Avatar";
import { harnessLabel, hueStyle } from "../../lib/agents";
import { pickFolder } from "../../lib/folder";
import { displayPath } from "../../lib/format";
import { useUi } from "../../store/ui";
import { reportError, useWorkspace } from "../../store/workspace";

const HANDLE = /^[a-z0-9_][a-z0-9_.:-]*$/;
const AVATAR_STYLE = "bottts";

/** Split a command line into argv, honouring double and single quotes. */
export function splitArgs(value: string): string[] {
  const args: string[] = [];
  const pattern = /"([^"]*)"|'([^']*)'|(\S+)/g;
  for (const match of value.matchAll(pattern)) args.push(match[1] ?? match[2] ?? match[3]);
  return args;
}

function joinArgs(args: string[]): string {
  return args.map((arg) => (/\s/.test(arg) ? `"${arg}"` : arg)).join(" ");
}

function randomSeed(): string {
  return Math.random().toString(36).slice(2, 10);
}

interface FormState {
  handle: string;
  description: string;
  harness: string;
  model: string;
  systemPrompt: string;
  tools: string[];
  defaultCwd: string;
  extraArgs: string;
  command: string;
  avatar: Avatar;
}

function initialState(agent: Agent | null): FormState {
  return {
    handle: agent?.handle ?? "",
    description: agent?.description ?? "",
    harness: agent?.harness ?? "",
    model: agent?.model ?? "",
    systemPrompt: agent?.system_prompt ?? "",
    tools: agent?.allowed_tools ?? [],
    defaultCwd: agent?.default_cwd ?? "",
    extraArgs: joinArgs(agent?.extra_args ?? []),
    command: joinArgs(agent?.command ?? []),
    avatar: agent?.avatar ?? { style: AVATAR_STYLE, seed: randomSeed() },
  };
}

export function AgentForm({ agentId }: { agentId: string | null }) {
  const agent = useWorkspace((s) => (agentId ? s.agents[agentId] ?? null : null));
  const view = useUi((s) => s.view);
  const navigate = useUi((s) => s.navigate);
  const openChannel = useUi((s) => s.openChannel);
  const queryClient = useQueryClient();
  const harnesses = useQuery({ queryKey: ["harnesses"], queryFn: api.harnesses });
  const [form, setForm] = useState<FormState>(() => initialState(agent));
  const [probe, setProbe] = useState<Harness | null>(null);
  const [probing, setProbing] = useState(false);
  const [scanning, setScanning] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [retiring, setRetiring] = useState(false);
  const [seeds] = useState(() => [randomSeed(), randomSeed(), randomSeed(), randomSeed()]);

  const returnTo = view.kind === "agent-new" || view.kind === "agent-edit" ? view.returnTo : undefined;
  const back = () => navigate(returnTo ?? { kind: "home" });
  const update = (patch: Partial<FormState>) => setForm((current) => ({ ...current, ...patch }));

  const catalog = useMemo(() => {
    if (form.harness === "custom" && probe) return probe;
    return harnesses.data?.find((h) => h.harness === form.harness) ?? null;
  }, [form.harness, harnesses.data, probe]);

  // Pick the first ready CLI for a new agent, then its default model.
  useEffect(() => {
    if (form.harness || !harnesses.data) return;
    const ready = harnesses.data.find((h) => h.found && h.harness !== "custom");
    if (ready) update({ harness: ready.harness });
  }, [harnesses.data, form.harness]);

  useEffect(() => {
    if (!catalog || !catalog.models.length) return;
    if (!catalog.models.some((m) => m.id === form.model)) {
      update({ model: (catalog.models.find((m) => m.default) ?? catalog.models[0]).id });
    }
    if (!catalog.capabilities.allowed_tools && form.tools.length) update({ tools: [] });
    else if (form.tools.some((t) => !catalog.tools.some((tool) => tool.id === t))) {
      update({ tools: form.tools.filter((t) => catalog.tools.some((tool) => tool.id === t)) });
    }
  }, [catalog]);

  const avatarOptions: Avatar[] = useMemo(() => {
    const current = agent?.avatar ?? form.avatar;
    return [current, ...seeds.map((seed) => ({ style: current.style || AVATAR_STYLE, seed }))];
  }, [agent?.avatar, seeds]);

  const scan = async () => {
    setScanning(true);
    try {
      const fresh = await api.scanHarnesses();
      queryClient.setQueryData(["harnesses"], fresh);
    } catch (err) {
      reportError(err);
    } finally {
      setScanning(false);
    }
  };

  const runProbe = async () => {
    const command = splitArgs(form.command);
    if (!command.length) return;
    setProbing(true);
    setError(null);
    try {
      setProbe(await api.probeCustom(command, splitArgs(form.extraArgs)));
    } catch (err) {
      setProbe(null);
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setProbing(false);
    }
  };

  const browse = async () => {
    const picked = await pickFolder("Default working directory", form.defaultCwd || null);
    if (picked) update({ defaultCwd: picked });
  };

  const handleValid = HANDLE.test(form.handle);
  const needsProbe = form.harness === "custom" && !probe && !agent;
  const canSave = handleValid && !!form.harness && !!form.model && !saving && !needsProbe;

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (!canSave) return;
    setSaving(true);
    setError(null);
    const input: AgentInput = {
      handle: form.handle,
      name: form.handle,
      description: form.description.trim(),
      harness: form.harness,
      model: form.model,
      system_prompt: form.systemPrompt,
      allowed_tools: catalog?.capabilities.allowed_tools ? form.tools : [],
      default_cwd: form.defaultCwd.trim() || null,
      avatar: form.avatar,
      extra_args: splitArgs(form.extraArgs),
      command: form.harness === "custom" ? splitArgs(form.command) : [],
    };
    try {
      const saved = agent ? await api.replaceAgent(agent.agent_id, input) : await api.createAgent(input);
      useWorkspace.getState().upsertAgent(saved);
      await useWorkspace.getState().refreshSummaries();
      if (!agent && saved.dm_channel_id) openChannel(saved.dm_channel_id);
      else back();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  };

  const retire = async () => {
    if (!agent) return;
    try {
      const retired = await api.retireAgent(agent.agent_id);
      useWorkspace.getState().upsertAgent(retired);
      await useWorkspace.getState().refreshSummaries();
      navigate({ kind: "home" });
    } catch (err) {
      reportError(err);
    }
  };

  const model = catalog?.models.find((m) => m.id === form.model);
  const previewAgent = { name: form.handle || "new-agent", hue: agent?.hue ?? Object.keys(useWorkspace.getState().agents).length % 8, avatar: form.avatar };
  const cliText = `${harnessLabel(form.harness || "cli")} · ${(model?.label ?? form.model) || "model"}`.toLowerCase();
  const cwdText = form.defaultCwd ? displayPath(form.defaultCwd) : null;

  return (
    <form className="form-screen fv-pane-glass" onSubmit={submit}>
      <header className="conversation-head">
        <button type="button" className="fv-icon-btn" aria-label="Back" onClick={back}><ChevronLeft /></button>
        <h1 className="conversation-title">{agent ? `Edit ${agent.handle}` : "New agent"}</h1>
        <span className="conversation-head-spacer" />
        {agent ? <button type="button" className="fv-btn fv-btn--danger" onClick={() => setRetiring(true)}>Retire agent</button> : null}
      </header>

      <div className="form-scroll">
        <div className="form-grid">
          <div className="form-main">
            <section className="form-section">
              <h2 className="fv-label">Identity</h2>
              <div className="fv-field">
                <span className="fv-field-label">Avatar</span>
                <div className="avatar-picker" role="radiogroup" aria-label="Avatar">
                  {avatarOptions.map((option) => {
                    const selected = option.seed === form.avatar.seed && option.style === form.avatar.style;
                    return (
                      <button type="button" key={`${option.style}:${option.seed}`} role="radio" aria-checked={selected}
                        className={`avatar-option${selected ? " is-selected" : ""}`} onClick={() => update({ avatar: option })}>
                        <AgentAvatar agent={{ ...previewAgent, avatar: option }} size="lg" />
                      </button>
                    );
                  })}
                </div>
              </div>
              <div className="form-row">
                <div className="fv-field">
                  <label htmlFor="agent-name">Name</label>
                  <input id="agent-name" className="fv-input fv-input--mono" placeholder="e.g. tester" value={form.handle}
                    autoFocus={!agent} onChange={(e) => update({ handle: e.target.value.toLowerCase().replace(/\s+/g, "-") })} />
                  <span className={form.handle && !handleValid ? "fv-error-text" : "fv-hint"}>
                    {form.handle && !handleValid ? "Use lowercase letters, digits, and - _ . :" : "Lowercase, used for @mentions."}
                  </span>
                </div>
                <div className="fv-field">
                  <label htmlFor="agent-description">Description</label>
                  <input id="agent-description" className="fv-input" placeholder="What is this agent for?" value={form.description}
                    onChange={(e) => update({ description: e.target.value })} />
                  <span className="fv-hint">Shown in @-mentions and used for routing.</span>
                </div>
              </div>
            </section>

            <section className="form-section">
              <div className="form-section-head">
                <h2 className="fv-label">Backing CLI</h2>
                <button type="button" className="fv-btn fv-btn--ghost fv-btn--sm" onClick={scan} disabled={scanning}>
                  <RefreshCw /> Scan again
                </button>
              </div>
              <div className="cli-grid" role="radiogroup" aria-label="Backing CLI">
                {(harnesses.data ?? []).map((harness) => (
                  <CliCard key={harness.harness} harness={harness} selected={form.harness === harness.harness}
                    onSelect={() => { update({ harness: harness.harness }); setError(null); }} />
                ))}
                {harnesses.isLoading ? <p className="fv-meta">Looking for CLIs on this machine…</p> : null}
              </div>
              {form.harness === "custom" ? (
                <div className="fv-field">
                  <label htmlFor="agent-command">Command</label>
                  <div className="path-row">
                    <input id="agent-command" className="fv-input fv-input--mono" placeholder="my-agent --stdio"
                      value={form.command} onChange={(e) => { update({ command: e.target.value }); setProbe(null); }} />
                    <button type="button" className="fv-btn" onClick={runProbe} disabled={probing || !form.command.trim()}>
                      {probing ? "Probing…" : "Probe"}
                    </button>
                  </div>
                  <span className="fv-hint">
                    {probe ? `Speaks the protocol · ${probe.models.length} models · ${probe.tools.length} tools`
                      : "Any command that speaks the Lgt stdio protocol. Probe it to load its models and tools."}
                  </span>
                </div>
              ) : null}
              <div className="fv-field">
                  <span className="fv-field-label">Model</span>
                  {catalog?.models.length ? (
                    <div className="fv-segmented model-picker" role="group" aria-label="Model">
                      {catalog.models.map((m) => (
                        <button type="button" key={m.id} aria-pressed={form.model === m.id} onClick={() => update({ model: m.id })}>
                          {m.label.toLowerCase()}
                        </button>
                      ))}
                    </div>
                  ) : (
                    <span className="fv-hint">{form.harness ? "This CLI reports no models yet." : "Choose a CLI first."}</span>
                  )}
                  {model ? <span className="fv-hint">{model.label} · {model.description}</span> : null}
              </div>
              <div className="form-row">
                <div className="fv-field">
                  <label htmlFor="agent-flags">Extra CLI flags</label>
                  <input id="agent-flags" className="fv-input fv-input--mono" placeholder="--max-turns 40" value={form.extraArgs}
                    onChange={(e) => update({ extraArgs: e.target.value })} />
                  <span className="fv-hint">Passed to every run. Optional.</span>
                </div>
              </div>
            </section>

            <section className="form-section">
              <h2 className="fv-label">Behaviour</h2>
              <div className="fv-field">
                <label htmlFor="agent-prompt">System prompt</label>
                <textarea id="agent-prompt" className="fv-textarea" placeholder="You review diffs for correctness…"
                  value={form.systemPrompt} onChange={(e) => update({ systemPrompt: e.target.value })} />
                <span className="fv-hint">{form.systemPrompt.length} characters · Markdown is fine.</span>
              </div>
            </section>

            <section className="form-section">
              <h2 className="fv-label">Tools and workspace</h2>
              <div className="fv-field">
                <span className="fv-field-label">Tool access</span>
                {catalog?.capabilities.allowed_tools ? (
                  <>
                    <div className="tool-chips" role="group" aria-label="Tool access">
                      {catalog.tools.map((tool) => {
                        const on = form.tools.includes(tool.id);
                        return (
                          <button type="button" key={tool.id} className={`fv-chip tool-chip${on ? " fv-chip--accent" : ""}`}
                            aria-pressed={on} title={tool.description}
                            onClick={() => update({ tools: on ? form.tools.filter((t) => t !== tool.id) : [...form.tools, tool.id] })}>
                            {on ? <Check /> : null}{tool.label}
                          </button>
                        );
                      })}
                    </div>
                    <span className="fv-hint">
                      {form.tools.length ? `Only these ${form.tools.length} tools are allowed.` : "No allowlist: the agent can use every tool its CLI provides."}
                    </span>
                  </>
                ) : (
                  <span className="fv-hint">
                    {catalog ? `${harnessLabel(catalog.harness)} doesn't enforce tool allowlists, so this agent can use every tool its CLI provides.` : "Choose a CLI first."}
                  </span>
                )}
              </div>
              <div className="fv-field">
                <label htmlFor="agent-cwd">Default working directory</label>
                <div className="path-row">
                  <input id="agent-cwd" className="fv-input fv-input--mono" placeholder="Used for this agent's DM. Optional."
                    value={form.defaultCwd} onChange={(e) => update({ defaultCwd: e.target.value })} />
                  <button type="button" className="fv-btn" onClick={browse}><Folder /> Browse…</button>
                </div>
              </div>
            </section>
            {error ? <p className="fv-error-text form-error" role="alert">{error}</p> : null}
          </div>

          <aside className="form-preview" aria-label="Preview">
            <h2 className="fv-label">Preview</h2>
            <div className="fv-card preview-card">
              <AgentAvatar agent={previewAgent} status="idle" size="xl" />
              <span className="fv-name preview-name" style={hueStyle(previewAgent)}>{form.handle || "new-agent"}</span>
              <p className="preview-desc">{form.description || "Add a description so routing knows when to pick this agent."}</p>
              <span className="fv-chip fv-chip--mono"><Terminal /> {cliText}</span>
            </div>
            <h2 className="fv-label">In the sidebar</h2>
            <div className="fv-card preview-row">
              <AgentAvatar agent={previewAgent} status="idle" />
              <span className="sidebar-row-text">
                <span className="sidebar-row-top">
                  <span className="fv-name">{form.handle || "new-agent"}</span>
                  <span className="fv-meta">now</span>
                </span>
                <span className="sidebar-row-line">{form.description || "Ready when you are"}</span>
              </span>
            </div>
            <h2 className="fv-label">In a channel</h2>
            <div className="fv-card preview-msg">
              <AgentAvatar agent={previewAgent} />
              <div>
                <div className="fv-msg-head">
                  <span className="fv-name" style={hueStyle(previewAgent)}>{form.handle || "new-agent"}</span>
                  <span className="fv-cli"><span className="via">via</span>{harnessLabel(form.harness || "cli")}</span>
                  <span className="fv-meta">now</span>
                </div>
                <p className="preview-text">
                  Hi — I'm set up in {cwdText ? <code>{cwdText}</code> : "my channel's directory"}
                  {catalog?.capabilities.allowed_tools && form.tools.length ? ` with ${form.tools.length} tools.` : "."}
                </p>
              </div>
            </div>
          </aside>
        </div>
      </div>

      <footer className="form-foot">
        <button type="button" className="fv-btn fv-btn--ghost" onClick={back}>Cancel</button>
        <button type="submit" className="fv-btn fv-btn--primary" disabled={!canSave}>
          {saving ? "Saving…" : agent ? "Save changes" : "Create agent"}
        </button>
      </footer>

      <Dialog.Root open={retiring} onOpenChange={setRetiring}>
        <Dialog.Portal>
          <Dialog.Overlay className="fv-dialog-overlay" />
          <Dialog.Content className="fv-dialog fv-glass">
            <Dialog.Title className="fv-dialog-title">Retire {agent?.handle}?</Dialog.Title>
            <Dialog.Description className="fv-dialog-desc">
              It leaves every channel, its queued work and runs are cancelled, and its DM is archived. Its history stays.
            </Dialog.Description>
            <div className="fv-dialog-actions">
              <Dialog.Close asChild><button type="button" className="fv-btn fv-btn--ghost">Keep agent</button></Dialog.Close>
              <button type="button" className="fv-btn fv-btn--danger" onClick={retire}>Retire</button>
            </div>
          </Dialog.Content>
        </Dialog.Portal>
      </Dialog.Root>
    </form>
  );
}

function CliCard({ harness, selected, onSelect }: { harness: Harness; selected: boolean; onSelect: () => void }) {
  const custom = harness.harness === "custom";
  const missing = !harness.found && !custom;
  const detail = custom
    ? "any command that speaks stdio"
    : harness.found
      ? [harness.path ? displayPath(harness.path, 34) : null, harness.version].filter(Boolean).join(" · ")
      : "not found on PATH";
  const badge = custom
    ? { text: "command", tone: "" }
    : missing
      ? { text: "install", tone: "fv-chip--failed" }
      : harness.auth === "signed_out"
        ? { text: "sign in", tone: "fv-chip--failed" }
        : { text: "detected", tone: "fv-chip--success" };
  return (
    <button type="button" role="radio" aria-checked={selected} disabled={missing}
      className={`cli-card${selected ? " is-selected" : ""}`} onClick={onSelect} title={detail}>
      <span className="fv-radio" data-checked={selected} />
      <span className="cli-icon"><Terminal /></span>
      <span className="cli-text">
        <span className="cli-name">{harnessLabel(harness.harness)}</span>
        <span className="cli-detail">{detail}</span>
      </span>
      <span className={`fv-chip ${badge.tone}`}>{badge.text}</span>
    </button>
  );
}
