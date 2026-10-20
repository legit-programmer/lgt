import type { CSSProperties } from "react";
import type { Agent, AgentStatus, Harness } from "../api/types";

/** Server hue indexes 0-7, in creation order. */
const HUES = ["violet", "sky", "pink", "green", "lime", "plum", "indigo", "sand"] as const;

export function hueName(hue: number | null | undefined): (typeof HUES)[number] {
  return HUES[((hue ?? 0) % HUES.length + HUES.length) % HUES.length];
}

export function hueVar(hue: number | null | undefined): string {
  return `var(--agent-${hueName(hue)})`;
}

export function hueStyle(agent: Pick<Agent, "hue"> | null | undefined): CSSProperties {
  return { "--h": hueVar(agent?.hue) } as CSSProperties;
}

export const HARNESS_LABEL: Record<string, string> = {
  claude: "claude",
  claude_code: "claude",
  codex: "codex",
  gemini: "gemini",
  custom: "custom",
};

export function harnessLabel(harness: string): string {
  return HARNESS_LABEL[harness] ?? harness;
}

const HARNESS_TITLE: Record<string, string> = {
  claude: "Claude", claude_code: "Claude", codex: "Codex", gemini: "Gemini", custom: "Custom",
};

/** "Claude · Sonnet" for cards: the catalog's model label as written, or the raw model id. */
export function cliTitle(agent: Agent, harnesses?: Harness[]): string {
  const catalog = harnesses?.find((h) => h.harness === agent.harness);
  const model = catalog?.models.find((m) => m.id === agent.model);
  return `${HARNESS_TITLE[agent.harness] ?? agent.harness} · ${model?.label ?? agent.model}`;
}

/** "claude · sonnet" using the catalog's label when one is known. */
export function cliLine(agent: Agent, harnesses?: Harness[]): string {
  const catalog = harnesses?.find((h) => h.harness === agent.harness);
  const model = catalog?.models.find((m) => m.id === agent.model);
  return `${harnessLabel(agent.harness)} · ${(model?.label ?? agent.model).toLowerCase()}`;
}

export function activeAgents(agents: Record<string, Agent>): Agent[] {
  return Object.values(agents)
    .filter((agent) => !agent.retired_at)
    .sort((a, b) => a.created_at.localeCompare(b.created_at));
}

export function isWorking(status: AgentStatus | undefined): boolean {
  return status?.state === "working";
}

export function initial(name: string): string {
  return (name.trim()[0] ?? "?").toUpperCase();
}
