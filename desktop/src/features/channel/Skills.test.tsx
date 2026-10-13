import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { SkillCatalog, SkillEntry } from "../../api/types";
import { useUi } from "../../store/ui";
import { Composer } from "./Composer";
import { SkillRecovery } from "./SkillRecovery";

const mocks = vi.hoisted(() => ({ channelSkills: vi.fn(), invokeSkill: vi.fn(), sendMessage: vi.fn(),
  commands: vi.fn(), addMember: vi.fn(), reportError: vi.fn() }));
vi.mock("../../api/client", () => ({ api: mocks }));
vi.mock("../../store/workspace", () => ({ reportError: mocks.reportError }));

const skill: SkillEntry = {
  skill_id: "claude-review", name: "review", description: "Review this project", harness: "claude",
  path: "/home/user/.claude/skills/review/SKILL.md", scope: "user", plugin_id: null,
  enabled: true, required_tools: ["Read"], unavailable_reason: null,
  agents: [{ agent_id: "coder", handle: "coder", in_channel: true, eligible: false, reason: "Requires claude; this agent uses codex", reason_code: "harness_mismatch" },
    { agent_id: "reviewer", handle: "reviewer", in_channel: true, eligible: true, reason: null, reason_code: null }],
  eligible_agent_ids: ["reviewer"], default_agent_id: null, recommended_agent_id: "reviewer",
  status: "choose_agent", reason: null,
};
let catalog: SkillCatalog;
let channelNumber = 0;
beforeEach(() => {
  vi.clearAllMocks();
  catalog = { channel_id: "channel", kind: "channel", skills: [skill], errors: [] };
  mocks.channelSkills.mockImplementation(async () => catalog);
  mocks.commands.mockResolvedValue([{ name: "/list", usage: "/list", description: "List skills" }]);
  mocks.invokeSkill.mockResolvedValue({});
  mocks.sendMessage.mockResolvedValue({});
});
afterEach(cleanup);

function setup(allowMentions = true, existingId?: string) {
  const channelId = existingId ?? `skills-test-${++channelNumber}`;
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={client}><Composer channelId={channelId} placeholder="Message" members={[]}
    allowMentions={allowMentions} reply={null} replyLoading={false} displayName="You" onClearReply={vi.fn()} />
  </QueryClientProvider>);
  return channelId;
}
async function selectSkill(command = "/") {
  fireEvent.change(screen.getByRole("textbox"), { target: { value: command, selectionStart: command.length } });
  fireEvent.mouseDown(await screen.findByRole("option", { name: /\/review/ }));
}

describe("skill discovery and invocation", () => {
  it("shows every harness and asks before routing to a compatible specialist", async () => {
    const channel = setup();
    await selectSkill();
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText(/Requires claude/)).toBeTruthy();
    expect(mocks.invokeSkill).not.toHaveBeenCalled();
    expect((screen.getByRole("button", { name: "Send", hidden: true }) as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(within(dialog).getByRole("button", { name: "Run with reviewer · recommended" }));
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "/review inspect code", selectionStart: 20 } });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    await waitFor(() => expect(mocks.invokeSkill).toHaveBeenCalledWith(channel, {
      skill_id: skill.skill_id, agent_id: "reviewer", arguments: "inspect code", attachments: [],
    }));
    expect(mocks.sendMessage).not.toHaveBeenCalled();
  });

  it("defaults to the server's primary and preserves distinct installations with identical names", async () => {
    catalog = { ...catalog, skills: [{ ...skill, status: "ready", default_agent_id: "reviewer" },
      { ...skill, skill_id: "codex-review", harness: "codex", status: "ready", default_agent_id: "coder", eligible_agent_ids: ["coder"] }] };
    setup();
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "/list", selectionStart: 5 } });
    const options = await screen.findAllByRole("option", { name: /\/review/ });
    expect(options).toHaveLength(2);
    fireEvent.mouseDown(options[0]);
    expect(screen.queryByRole("dialog")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    await waitFor(() => expect(mocks.invokeSkill).toHaveBeenCalled());
    expect(mocks.invokeSkill.mock.calls[0][1].skill_id).toBe("claude-review");
    expect(mocks.invokeSkill.mock.calls[0][1].agent_id).toBe("reviewer");
  });

  it("offers an explicit DM backend switch and preserves the draft", async () => {
    catalog = { ...catalog, kind: "dm", skills: [{ ...skill, agents: [skill.agents[0]],
      status: "unavailable", eligible_agent_ids: [], recommended_agent_id: null, reason: "No compatible agent in this DM" }] };
    const channelId = setup(false);
    await selectSkill();
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).queryByRole("button", { name: /Create/ })).toBeNull();
    fireEvent.click(within(dialog).getByRole("button", { name: "Switch to claude" }));
    expect(useUi.getState().view).toEqual({ kind: "agent-edit", agentId: "coder", harness: "claude",
      returnTo: { kind: "channel", channelId } });
    expect((screen.getByRole("textbox") as HTMLTextAreaElement).value).toBe("/review ");
    expect(mocks.invokeSkill).not.toHaveBeenCalled();
  });

  it("offers channel creation without automatically changing an existing agent", async () => {
    catalog = { ...catalog, skills: [{ ...skill, agents: [skill.agents[0]], status: "unavailable", eligible_agent_ids: [],
      recommended_agent_id: null, reason: "No compatible agent" }] };
    const channelId = setup();
    await selectSkill();
    fireEvent.click(await screen.findByRole("button", { name: "Create a claude agent" }));
    expect(useUi.getState().view).toEqual({ kind: "agent-new", harness: "claude", addToChannelId: channelId,
      returnTo: { kind: "channel", channelId } });
    expect(mocks.invokeSkill).not.toHaveBeenCalled();
  });

  it("rechecks manually typed skills and retains arguments when execution is rejected", async () => {
    setup();
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "/review my arguments", selectionStart: 20 } });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    const dialog = await screen.findByRole("dialog");
    expect(mocks.invokeSkill).not.toHaveBeenCalled();
    fireEvent.click(within(dialog).getByRole("button", { name: "Run with reviewer · recommended" }));
    mocks.invokeSkill.mockRejectedValueOnce(new Error("Agent no longer allows Write"));
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    await waitFor(() => expect(mocks.reportError).toHaveBeenCalled());
    expect((screen.getByRole("textbox", { hidden: true }) as HTMLTextAreaElement).value).toBe("/review my arguments");
    expect(await screen.findByRole("dialog")).toBeTruthy();
  });

  it("restores the selected installation, executor, and arguments after switching conversations", async () => {
    const channel = setup();
    await selectSkill();
    fireEvent.click(await screen.findByRole("button", { name: "Run with reviewer · recommended" }));
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "/review saved arguments" } });
    cleanup();
    setup(true, channel);
    await waitFor(() => expect((screen.getByRole("button", { name: "Send" }) as HTMLButtonElement).disabled).toBe(false));
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    await waitFor(() => expect(mocks.invokeSkill).toHaveBeenCalledWith(channel, {
      skill_id: skill.skill_id, agent_id: "reviewer", arguments: "saved arguments", attachments: [],
    }));
  });

  it("blocks a restored selection when fresh server eligibility has changed", async () => {
    const channel = setup();
    await selectSkill();
    fireEvent.click(await screen.findByRole("button", { name: "Run with reviewer · recommended" }));
    cleanup();
    catalog = { ...catalog, skills: [{ ...skill, eligible_agent_ids: [], status: "unavailable", recommended_agent_id: null,
      reason: "Agent no longer allows Read", agents: skill.agents.map((agent) => ({ ...agent, eligible: false })) }] };
    setup(true, channel);
    await waitFor(() => expect(mocks.channelSkills).toHaveBeenCalledTimes(2));
    expect((screen.getByRole("button", { name: "Send" }) as HTMLButtonElement).disabled).toBe(true);
    expect(mocks.invokeSkill).not.toHaveBeenCalled();
  });

  it("offers an explicitly selected executor after runtime permission failure", async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(<QueryClientProvider client={client}><SkillRecovery channelId="channel" payload={{
      run_id: "failed-run", agent_id: "coder", status: "failed", started_at: null, ended_at: null, duration_ms: null,
      skill: { ...skill, arguments: "original arguments", agent_id: "coder" },
      error: { code: "permission", message: "Write was denied", exit_code: null, signal: null },
    }} /></QueryClientProvider>);
    fireEvent.click(screen.getByRole("button", { name: "Choose an executor and retry" }));
    const dialog = await screen.findByRole("dialog");
    expect(mocks.invokeSkill).not.toHaveBeenCalled();
    fireEvent.click(within(dialog).getByRole("button", { name: "Run with reviewer · recommended" }));
    await waitFor(() => expect(mocks.invokeSkill).toHaveBeenCalledWith("channel", {
      skill_id: skill.skill_id, agent_id: "reviewer", arguments: "original arguments",
    }));
  });
});
