import * as Popover from "@radix-ui/react-popover";
import { useQuery } from "@tanstack/react-query";
import { Check, SlidersHorizontal, X } from "lucide-react";
import { useEffect, useId, useRef, useState, type ReactNode } from "react";
import { api } from "../api/client";
import type { Agent, HarnessModel } from "../api/types";
import { harnessLabel, hueStyle } from "../lib/agents";
import { ProviderLogo } from "./ProviderLogo";
import "./AgentInference.css";

export function AgentInference({ agent, children }: { agent: Agent; children: ReactNode }) {
  const [open, setOpen] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const pinned = useRef(false);
  const cancel = () => { if (timer.current) clearTimeout(timer.current); timer.current = null; };
  useEffect(() => cancel, []);
  const enter = () => { cancel(); timer.current = setTimeout(() => setOpen(true), 220); };
  const leave = () => { cancel(); if (!pinned.current) timer.current = setTimeout(() => setOpen(false), 350); };
  return (
    <Popover.Root open={open} onOpenChange={(value) => { cancel(); pinned.current = value; setOpen(value); }}>
      <Popover.Trigger asChild>
        <button type="button" className="fv-agent-inference-trigger" style={hueStyle(agent)}
          aria-label={`Model and reasoning for ${agent.handle}`} onPointerEnter={enter} onPointerLeave={leave}
          onFocus={enter} onClick={(event) => { event.preventDefault(); cancel(); pinned.current = true; setOpen(true); }}>
          {children}
        </button>
      </Popover.Trigger>
      <Popover.Portal>
        <Popover.Content className="fv-inference-panel fv-glass" style={hueStyle(agent)} side="bottom" align="start" sideOffset={8}
          collisionPadding={12} aria-label={`${agent.handle} model and reasoning`}
          onPointerEnter={cancel} onPointerLeave={leave} onFocusCapture={() => { cancel(); pinned.current = true; }}
          onOpenAutoFocus={(event) => { if (!pinned.current) event.preventDefault(); }}
          onCloseAutoFocus={(event) => event.preventDefault()}>
          <InferenceEditor agent={agent} />
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  );
}

function InferenceEditor({ agent }: { agent: Agent }) {
  const models = useQuery({ queryKey: ["agent-models", agent.agent_id, agent.harness], queryFn: () => api.agentModels(agent.agent_id) });
  const [modelId, setModelId] = useState(agent.model);
  const [effort, setEffort] = useState<string | null>(agent.reasoning_effort ?? null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [submitted, setSubmitted] = useState(false);
  const id = useId();
  const model = models.data?.find((item) => item.id === modelId);
  const modes = model?.reasoning_modes ?? [];
  const effective = effort ?? model?.default_reasoning_effort;
  const index = modes.findIndex((mode) => mode.id === effective);
  const selected = index >= 0 ? modes[index] : undefined;
  const dirty = modelId !== agent.model || effort !== (agent.reasoning_effort ?? null);
  const pending = submitted && dirty;
  useEffect(() => {
    if (!dirty) setSubmitted(false);
  }, [dirty]);
  const save = async () => {
    setSaving(true); setError(null); setSubmitted(false);
    try {
      await api.updateAgentInference(agent.agent_id, { model: modelId, reasoning_effort: effort });
      setSubmitted(true);
    } catch (failure) { setError(failure instanceof Error ? failure.message : String(failure)); }
    finally { setSaving(false); }
  };
  const locked = saving || pending || !!agent.retired_at;
  const pickModel = (next: HarnessModel) => {
    setModelId(next.id); setEffort(next.default_reasoning_effort ?? null); setSubmitted(false); setError(null);
  };
  const pickEffort = (next: string | null) => { setEffort(next); setSubmitted(false); setError(null); };
  return (
    <>
      <header className="fv-inference-header">
        <span className="fv-inference-provider"><ProviderLogo harness={agent.harness} /></span>
        <div><span className="fv-name" style={hueStyle(agent)}>{agent.handle}</span><span className="fv-inference-subtitle">via {harnessLabel(agent.harness)}</span></div>
        <Popover.Close asChild><button className="fv-icon-btn fv-icon-btn--sm" aria-label="Close agent settings"><X /></button></Popover.Close>
      </header>
      {models.isPending ? <p className="fv-meta fv-inference-state" role="status">Loading available models…</p> : models.isError ? (
        <div className="fv-inference-state" role="alert"><p className="fv-meta">Could not load this provider's models.</p><button className="fv-btn fv-btn--sm" onClick={() => void models.refetch()}>Retry</button></div>
      ) : (
        <>
          <fieldset className="fv-inference-field" disabled={locked}>
            <legend className="fv-label">Model</legend>
            <div className="fv-inference-models">
              {!model ? (
                <label className="fv-inference-model">
                  <input type="radio" name={`${id}-model`} checked readOnly aria-label={`${modelId} · unavailable`} />
                  <span className="fv-inference-model-text"><span className="fv-inference-model-name">{modelId}</span><span className="fv-inference-model-desc">Not in the current provider catalog</span></span>
                  <span className="fv-inference-check" aria-hidden="true"><Check /></span>
                </label>
              ) : null}
              {models.data?.map((item) => (
                <label key={item.id} className="fv-inference-model">
                  <input type="radio" name={`${id}-model`} value={item.id} checked={item.id === modelId} aria-label={item.label}
                    onChange={() => pickModel(item)} />
                  <span className="fv-inference-model-text"><span className="fv-inference-model-name">{item.label}</span><span className="fv-inference-model-desc">{item.description}</span></span>
                  <span className="fv-inference-check" aria-hidden="true"><Check /></span>
                </label>
              ))}
            </div>
          </fieldset>
          <fieldset className="fv-inference-field" disabled={locked}>
            <div className="fv-inference-level">
              <span className="fv-label">Reasoning</span>
              {modes.length ? (
                <button type="button" className="fv-inference-default" aria-pressed={effort === null} onClick={() => pickEffort(null)}>
                  {effort === null ? <Check aria-hidden="true" /> : null}Provider default
                </button>
              ) : null}
            </div>
            {modes.length ? (
              <>
                <div className="fv-inference-meter" role="radiogroup" aria-label="Reasoning" data-default={effort === null}
                  style={{ gridTemplateColumns: `repeat(${modes.length}, minmax(0, 1fr))` }}>
                  {modes.map((mode, position) => (
                    <label key={mode.id} className="fv-inference-step" data-filled={index >= 0 && position <= index} data-selected={position === index}>
                      <input type="radio" name={`${id}-effort`} value={mode.id} checked={effort === mode.id} aria-label={mode.label}
                        onChange={() => pickEffort(mode.id)} />
                      <span className="fv-inference-bar" aria-hidden="true" />
                      <span className="fv-inference-step-label">{mode.label}</span>
                    </label>
                  ))}
                </div>
                <p className="fv-inference-hint">
                  <span className="fv-inference-value">{selected?.label ?? "Provider default"}</span>
                  {selected?.description ?? "Uses the provider's default reasoning mode."}
                </p>
              </>
            ) : <p className="fv-inference-hint">This model's CLI manages reasoning automatically.</p>}
          </fieldset>
          {error ? <p className="fv-inference-error" role="alert">{error}</p> : null}
          <footer className="fv-inference-footer"><span className="fv-meta">Applies to the next run</span>
            <button className="fv-btn fv-btn--primary fv-btn--sm" disabled={!dirty || !model || locked} onClick={() => void save()}>
              {saving || pending ? "Saving…" : submitted ? <><Check /> Saved</> : <><SlidersHorizontal /> Apply</>}
            </button>
          </footer>
        </>
      )}
    </>
  );
}
