import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "../../api/client";
import type { RunStatusPayload } from "../../api/types";
import { useUi } from "../../store/ui";
import { reportError } from "../../store/workspace";
import { SkillDialog } from "./SkillDialog";

export function SkillRecovery({ channelId, payload }: { channelId: string; payload: RunStatusPayload }) {
  const [open, setOpen] = useState(false);
  const [retrying, setRetrying] = useState(false);
  const navigate = useUi((state) => state.navigate);
  const skills = useQuery({ queryKey: ["skill-recovery", channelId, payload.run_id],
    queryFn: () => api.channelSkills(channelId), enabled: open, staleTime: 0, retry: false });
  const skill = skills.data?.skills.find((entry) => entry.skill_id === payload.skill?.skill_id);
  const retry = async (agentId: string) => {
    if (!skill || retrying) return;
    setRetrying(true);
    try {
      await api.invokeSkill(channelId, { skill_id: skill.skill_id, agent_id: agentId, arguments: payload.skill?.arguments });
      setOpen(false);
    } catch (error) { reportError(error); await skills.refetch(); }
    finally { setRetrying(false); }
  };
  return <>
    <button className="fv-btn fv-btn--sm" onClick={() => navigate({ kind: "agent-edit", agentId: payload.agent_id,
      returnTo: { kind: "channel", channelId } })}>Change agent permissions or backend</button>
    {payload.skill ? <button className="fv-btn fv-btn--sm" disabled={retrying} onClick={() => setOpen(true)}>Choose an executor and retry</button> : null}
    {open && skills.isFetching ? <span className="fv-meta">Refreshing skill availability…</span> : null}
    {open && skills.error ? <span className="fv-error-text">{skills.error.message}</span> : null}
    {open && skills.data && !skill ? <span className="fv-error-text">This skill installation is no longer available. Open /list to choose another installation.</span> : null}
    {open && skill ? <SkillDialog channelId={channelId} skill={skill} kind={skills.data!.kind}
      onRefresh={() => skills.refetch()} onClose={() => setOpen(false)} onChoose={(agentId) => void retry(agentId)} /> : null}
  </>;
}
