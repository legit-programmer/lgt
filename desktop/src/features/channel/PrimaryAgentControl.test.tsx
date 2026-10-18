import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Agent, ChannelSummary } from "../../api/types";
import { PrimaryAgentControl } from "./ChannelScreen";

const mocks = vi.hoisted(() => ({ setPrimary: vi.fn() }));
vi.mock("../../api/client", () => ({ api: mocks }));
vi.mock("../../components/Avatar", () => ({ AgentAvatar: () => <span aria-hidden="true" /> }));

const agent = { agent_id: "a1", handle: "builder", retired_at: null } as Agent;
const channel = {
  channel_id: "c1", kind: "channel", name: "work", primary_agent_id: null,
  routing_mode: "unassigned", active_runs: [],
} as unknown as ChannelSummary;

beforeEach(() => {
  vi.clearAllMocks();
  mocks.setPrimary.mockResolvedValue({});
});
afterEach(cleanup);

describe("primary assignment", () => {
  it("waits for server state after PATCH before showing the new primary", async () => {
    const view = render(<PrimaryAgentControl channel={channel} members={[agent]} />);
    fireEvent.keyDown(screen.getByRole("button", { name: "Choose a primary agent" }), { key: "Enter" });
    fireEvent.click(await screen.findByRole("menuitem", { name: /builder/ }));
    await waitFor(() => expect(mocks.setPrimary).toHaveBeenCalledWith("c1", "a1"));

    expect(screen.getByRole("button", { name: "Choose a primary agent" })).toBeTruthy();
    view.rerender(<PrimaryAgentControl channel={{ ...channel, primary_agent_id: "a1", routing_mode: "primary" }} members={[agent]} />);
    expect(screen.getByRole("button", { name: "Primary agent: builder" })).toBeTruthy();
  });
});
