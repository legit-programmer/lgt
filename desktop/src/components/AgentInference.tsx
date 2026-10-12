import * as Popover from "@radix-ui/react-popover";
import { useQuery } from "@tanstack/react-query";
import { Check, ChevronDown, SlidersHorizontal, X } from "lucide-react";
import { useEffect, useId, useRef, useState, type ReactNode } from "react";
import { api } from "../api/client";
import type { Agent } from "../api/types";
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
        <Popover.Content className="fv-inference-panel fv-glass" side="bottom" align="start" sideOffset={8}
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
  return (
    <>
      <header className="fv-inference-header">
        <span className="fv-inference-provider"><ProviderLogo harness={agent.harness} /></span>
        <div><span className="fv-name" style={hueStyle(agent)}>{agent.handle}</span><span className="fv-inference-subtitle">{harnessLabel(agent.harness)} · Agent settings</span></div>
        <Popover.Close asChild><button className="fv-icon-btn fv-icon-btn--sm" aria-label="Close agent settings"><X /></button></Popover.Close>
      </header>
      {models.isPending ? <p className="fv-meta" role="status">Loading available models…</p> : models.isError ? (
        <div role="alert"><p className="fv-meta">Could not load this provider's models.</p><button className="fv-btn fv-btn--sm" onClick={() => void models.refetch()}>Retry</button></div>
      ) : (
        <>
          <div className="fv-inference-field">
            <label className="fv-label" htmlFor={`${id}-model`}>Model</label>
            <div className="fv-inference-select"><select id={`${id}-model`} className="fv-input" value={modelId} disabled={saving || pending || !!agent.retired_at || !models.data?.length}
              onChange={(event) => {
                const next = models.data?.find((item) => item.id === event.target.value);
                setModelId(event.target.value); setEffort(next?.default_reasoning_effort ?? null); setSubmitted(false); setError(null);
              }}>
              {!model ? <option value={modelId}>{modelId} · unavailable</option> : null}
              {models.data?.map((item) => <option key={item.id} value={item.id}>{item.label}</option>)}
            </select><ChevronDown aria-hidden="true" /></div>
            <p className="fv-meta">{model?.description ?? "This model is not in the current provider catalog."}</p>
          </div>
          <div className="fv-inference-field">
            <div className="fv-inference-level"><label className="fv-label" htmlFor={`${id}-effort`}>Reasoning</label><span className="fv-inference-value">{selected?.label ?? (modes.length ? "Provider default" : "Automatic")}</span></div>
            {modes.length ? (
              <>
                <input id={`${id}-effort`} className="fv-inference-slider" type="range" min={0} max={Math.max(0, modes.length - 1)} step={1} value={Math.max(0, index)}
                  aria-valuetext={selected?.label ?? "Provider default"} disabled={saving || pending || !!agent.retired_at || modes.length === 1}
                  onChange={(event) => { setEffort(modes[Number(event.target.value)].id); setError(null); setSubmitted(false); }} />
                <div className="fv-inference-ticks" aria-hidden="true">{modes.map((mode) => <span key={mode.id} data-selected={mode.id === effective}>{mode.label}</span>)}</div>
                <p className="fv-meta">{selected?.description ?? "Uses the provider's default reasoning mode."}</p>
                <button className="fv-inference-default" disabled={saving || pending || effort === null} onClick={() => { setEffort(null); setSubmitted(false); }}>Use provider default</button>
              </>
            ) : <p className="fv-meta">This model's CLI manages reasoning automatically.</p>}
          </div>
          {error ? <p className="fv-inference-error" role="alert">{error}</p> : null}
          <footer className="fv-inference-footer"><span className="fv-meta">Applies to the next run.</span>
            <button className="fv-btn fv-btn--primary fv-btn--sm" disabled={!dirty || !model || saving || pending || !!agent.retired_at} onClick={() => void save()}>
              {saving || pending ? "Saving…" : submitted ? <><Check /> Saved</> : <><SlidersHorizontal /> Apply</>}
            </button>
          </footer>
        </>
      )}
    </>
  );
}
