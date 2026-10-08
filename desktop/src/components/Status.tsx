import { Check, Clock } from "lucide-react";
import type { AgentStatus } from "../api/types";
import { useNow } from "../lib/useNow";
import { clock } from "../lib/format";

type State = AgentStatus["state"] | "success";

export function WorkingDots() {
  return (
    <span className="fv-working-dots" aria-hidden="true">
      <i />
      <i />
      <i />
    </span>
  );
}

/** The avatar-corner dot: ring idle, dots working, square failed, clock queued. */
export function StatusDot({ state }: { state: State }) {
  if (state === "working") {
    return <span className="fv-dot fv-dot--working"><WorkingDots /></span>;
  }
  if (state === "queued") {
    return <span className="fv-dot fv-dot--queued"><Clock size={9} strokeWidth={2.5} /></span>;
  }
  if (state === "failed") return <span className="fv-dot fv-dot--failed" />;
  return <span className="fv-dot fv-dot--idle" />;
}

/** Elapsed time since an ISO timestamp, ticking every second. */
export function Elapsed({ since }: { since: string | null | undefined }) {
  const now = useNow(1000);
  if (!since) return <>0:00</>;
  return <>{clock(now - new Date(since).getTime())}</>;
}

interface StatusBadgeProps {
  state: State;
  since?: string | null;
  label?: string;
  plain?: boolean;
}

/** Glyph + word (+ live clock) for a status. Never colour alone. */
export function StatusBadge({ state, since, label, plain }: StatusBadgeProps) {
  const className = `fv-status fv-status--${state}${plain ? " fv-status--plain" : ""}`;
  if (state === "working") {
    return (
      <span className={className}>
        <WorkingDots />
        <span className="fv-status-text">{label ?? "working"} {since !== undefined ? <Elapsed since={since} /> : null}</span>
      </span>
    );
  }
  if (state === "queued") {
    return <span className={className}><Clock />{label ?? "queued"}</span>;
  }
  if (state === "failed") {
    return <span className={className}><span className="fv-dot fv-dot--failed" style={{ boxShadow: "none", background: "transparent" }} />{label ?? "failed"}</span>;
  }
  if (state === "success") {
    return <span className={className}><Check />{label ?? "done"}</span>;
  }
  return <span className={className}><span className="fv-dot fv-dot--idle" style={{ boxShadow: "none", background: "transparent" }} />{label ?? "idle"}</span>;
}
