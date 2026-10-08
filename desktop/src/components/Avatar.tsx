import { createAvatar, type Style } from "@dicebear/core";
import * as collection from "@dicebear/collection";
import { useMemo } from "react";
import type { Agent, AgentStatus, Avatar as AvatarSpec } from "../api/types";
import { hueStyle, initial } from "../lib/agents";
import { StatusDot } from "./Status";

const styles = collection as unknown as Record<string, Style<object>>;
const cache = new Map<string, string>();

function camel(style: string): string {
  return style.replace(/-([a-z0-9])/g, (_, char: string) => char.toUpperCase());
}

/** A DiceBear data URI rendered locally, so avatars work offline. */
export function avatarUri(spec: AvatarSpec): string | null {
  const key = `${spec.style}:${spec.seed}`;
  const cached = cache.get(key);
  if (cached) return cached;
  const style = styles[camel(spec.style)];
  if (!style) return null;
  const uri = createAvatar(style, { seed: spec.seed }).toDataUri();
  cache.set(key, uri);
  return uri;
}

interface AgentAvatarProps {
  agent: Pick<Agent, "name" | "hue" | "avatar"> | null | undefined;
  status?: AgentStatus["state"] | null;
  size?: "md" | "lg" | "xl";
  className?: string;
}

export function AgentAvatar({ agent, status, size = "md", className = "" }: AgentAvatarProps) {
  const uri = useMemo(() => (agent?.avatar ? avatarUri(agent.avatar) : null), [agent?.avatar]);
  const sizeClass = size === "md" ? "" : ` fv-avatar--${size}`;
  return (
    <span className={`fv-avatar${sizeClass} ${className}`} style={hueStyle(agent)} aria-hidden="true">
      {uri ? <img src={uri} alt="" draggable={false} /> : initial(agent?.name ?? "?")}
      {status ? <StatusDot state={status} /> : null}
    </span>
  );
}

export function PersonAvatar({ name, size = "md" }: { name: string; size?: "md" | "lg" }) {
  return (
    <span className={`fv-avatar fv-avatar--person${size === "lg" ? " fv-avatar--lg" : ""}`} aria-hidden="true">
      {initial(name)}
    </span>
  );
}
