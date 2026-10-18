import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Agent } from "../../api/types";
import { useUi } from "../../store/ui";
import { useWorkspace } from "../../store/workspace";
import { NewChannelDialog } from "./NewChannelDialog";

const mocks = vi.hoisted(() => ({ createChannel: vi.fn(), channels: vi.fn(), agentStatuses: vi.fn(), reportError: vi.fn() }));
vi.mock("../../api/client", () => ({ api: mocks }));

function makeAgent(id: string, handle: string): Agent {
  return {
    agent_id: id, handle, name: handle, description: `${handle} agent`, harness: "codex", model: "m",
    reasoning_effort: null, system_prompt: "", allowed_tools: [], default_cwd: null, permission_mode: "full",
    created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z", avatar: { style: "critters", seed: id },
    hue: 0, extra_args: [], command: [], retired_at: null, dm_channel_id: null,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  mocks.channels.mockResolvedValue([]);
  mocks.agentStatuses.mockResolvedValue([]);
  mocks.createChannel.mockResolvedValue({ channel_id: "c1" });
  useWorkspace.setState({ agents: { a1: makeAgent("a1", "builder"), a2: makeAgent("a2", "reviewer") } });
  useUi.setState({ newChannelOpen: true });
});
afterEach(cleanup);

describe("new channel setup", () => {
  it("requires a selected agent and explicit primary, then sends both to the server", async () => {
    render(<NewChannelDialog />);
    const create = screen.getByRole("button", { name: "Create channel" }) as HTMLButtonElement;
    expect(create.disabled).toBe(true);

    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "review" } });
    fireEvent.click(screen.getByRole("button", { name: /builder/ }));
    expect(create.disabled).toBe(true);

    const primary = screen.getByLabelText("Primary agent") as HTMLSelectElement;
    fireEvent.change(primary, { target: { value: "a1" } });
    expect(create.disabled).toBe(false);

    fireEvent.click(screen.getByRole("button", { name: /builder/ }));
    expect(primary.value).toBe("");
    expect(create.disabled).toBe(true);

    fireEvent.click(screen.getByRole("button", { name: /reviewer/ }));
    fireEvent.change(primary, { target: { value: "a2" } });
    fireEvent.click(create);

    await waitFor(() => expect(mocks.createChannel).toHaveBeenCalledWith({
      name: "review", kind: "channel", agent_ids: ["a2"], primary_agent_id: "a2", cwd: null,
    }));
  });
});
