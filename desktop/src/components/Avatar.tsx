import { Avatar as DiceBearAvatar, Style, type StyleDefinition } from "@dicebear/core";
import { useEffect, useState } from "react";
import type { Agent, AgentStatus, Avatar as AvatarSpec } from "../api/types";
import { hueStyle, initial } from "../lib/agents";
import { StatusDot } from "./Status";

/*
 * Agent avatars are DiceBear avatars rendered locally from the {style, seed}
 * the backend stores, so they work offline. Each style's definition
 * (@dicebear/styles) is its own chunk, loaded the first time it is used; the
 * default style is Critters (CC0).
 */

const definitions = import.meta.glob<StyleDefinition>("/node_modules/@dicebear/styles/dist/*.min.json", {
  import: "default",
});

const styles = new Map<string, Promise<Style | null>>();
const uris = new Map<string, string>();

function loadStyle(name: string): Promise<Style | null> {
  let pending = styles.get(name);
  if (!pending) {
    const load = definitions[`/node_modules/@dicebear/styles/dist/${name}.min.json`];
    pending = load ? load().then((definition) => new Style(definition)).catch(() => null) : Promise.resolve(null);
    styles.set(name, pending);
  }
  return pending;
}

function cachedUri(spec: AvatarSpec): string | undefined {
  return uris.get(`${spec.style}:${spec.seed}`);
}

/** A DiceBear data URI for the spec, or null while loading or for an unknown style. */
export function useAvatarUri(spec: AvatarSpec | null | undefined): string | null {
  const [uri, setUri] = useState<string | null>(() => (spec ? cachedUri(spec) ?? null : null));
  const style = spec?.style;
  const seed = spec?.seed;
  useEffect(() => {
    if (!style || !seed) {
      setUri(null);
      return;
    }
    const key = `${style}:${seed}`;
    const cached = uris.get(key);
    if (cached) {
      setUri(cached);
      return;
    }
    let live = true;
    void loadStyle(style).then((loaded) => {
      if (!loaded) {
        if (live) setUri(null);
        return;
      }
      const rendered = new DiceBearAvatar(loaded, { seed }).toDataUri();
      uris.set(key, rendered);
      if (live) setUri(rendered);
    });
    return () => {
      live = false;
    };
  }, [style, seed]);
  return uri;
}

interface AgentAvatarProps {
  agent: Pick<Agent, "name" | "hue" | "avatar"> | null | undefined;
  status?: AgentStatus["state"] | null;
  size?: "md" | "lg" | "xl";
  className?: string;
}

export function AgentAvatar({ agent, status, size = "md", className = "" }: AgentAvatarProps) {
  const uri = useAvatarUri(agent?.avatar);
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
