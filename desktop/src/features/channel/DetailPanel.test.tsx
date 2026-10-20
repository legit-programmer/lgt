import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import type { Agent, ChannelSummary, Run } from "../../api/types";
import { useUi } from "../../store/ui";
import { useWorkspace } from "../../store/workspace";
import { DetailPanel } from "./DetailPanel";

const mocks = vi.hoisted(() => ({ runs: vi.fn(), harnesses: vi.fn(), removeMember: vi.fn() }));
vi.mock("../../api/client", () => ({ api: mocks }));
vi.mock("../../components/ProviderLogo", () => ({ ProviderLogo: () => <span /> }));
vi.mock("../../components/AgentInference", () => ({ AgentInference: ({ children }: { children: ReactNode }) => <>{children}</> }));

const agent = { agent_id: "a1", handle: "builder", harness: "codex", model: "m", reasoning_effort: null, retired_at: null } as Agent;
const channel = { channel_id: "c1", name: "work", kind: "channel", cwd: "/home/sam/work", cwd_managed: false, allow_handoff: true, primary_agent_id: "a1", active_runs: [] } as unknown as ChannelSummary;
const run = { run_id: "r1", agent_id: "a1", channel_id: "c1", status: "failed", started_at: new Date().toISOString(), tokens_total: 2400 } as Run;

beforeEach(() => {
  mocks.runs.mockResolvedValue([run]);
  mocks.harnesses.mockResolvedValue([]);
  mocks.removeMember.mockResolvedValue({});
  useUi.setState({ detailTab: "agents", detailOpen: true });
  useWorkspace.setState({
    statuses: { a1: { agent_id: "a1", state: "idle", active_runs: [], activity: null, last_failure: null } },
    contexts: { "c1:a1": { channel_id: "c1", agent_id: "a1", mode: "resume", start_seq: 1, messages_in_context: 12,
      context_tokens: 41_000, model_context_window: 200_000, checkpoint_seq: null } },
    usage: [{ agent: "a1", run_count: 3, tokens_in: 0, tokens_out: 0, tokens_cached_in: 0, tokens_cache_creation: 0,
      tokens_reasoning: 0, tokens_total: 9_000 }],
    runs: {},
  });
});
afterEach(() => { cleanup(); vi.clearAllMocks(); });

function mount() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={client}><DetailPanel channel={channel} members={[agent]} /></QueryClientProvider>);
}

it("shows the server's last run, context and usage on the agent card", async () => {
  mount();
  const last = await screen.findByRole("button", { name: /Failed · now · 2.4k tokens/ });
  expect(mocks.runs).toHaveBeenCalledWith({ channel_id: "c1", agent_id: "a1", limit: 1 });
  expect(screen.getByText("41k of 200k")).toBeTruthy();
  expect(screen.getByRole("meter", { name: "Context window used" }).getAttribute("aria-valuenow")).toBe("21");
  expect(screen.getByText("12 messages")).toBeTruthy();
  expect(screen.getByText("9k tokens · 3 runs")).toBeTruthy();
  fireEvent.click(last);
  expect(useUi.getState()).toMatchObject({ detailTab: "run", runFilterAgentId: "a1", selectedRunId: "r1" });
});

it("keeps removal behind a menu and a confirmation", async () => {
  mount();
  expect(screen.queryByRole("button", { name: /^Remove/ })).toBeNull();
  fireEvent.keyDown(screen.getByRole("button", { name: "More actions for builder" }), { key: "Enter" });
  fireEvent.click(await screen.findByRole("menuitem", { name: "Remove from #work" }));
  fireEvent.click(await screen.findByRole("button", { name: "Remove" }));
  await waitFor(() => expect(mocks.removeMember).toHaveBeenCalledWith("c1", "a1"));
});
