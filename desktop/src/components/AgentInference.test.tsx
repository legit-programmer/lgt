import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import type { Agent, HarnessModel } from "../api/types";
import { AgentInference } from "./AgentInference";

const mocks = vi.hoisted(() => ({ models: vi.fn(), update: vi.fn() }));
vi.mock("../api/client", () => ({ api: { agentModels: mocks.models, updateAgentInference: mocks.update } }));
vi.mock("./ProviderLogo", () => ({ ProviderLogo: () => <span /> }));
const modes = [
  { id: "low", label: "Low", description: "Quick replies" },
  { id: "high", label: "High", description: "More deliberate reasoning" },
];
const catalog: HarnessModel[] = [
  { id: "a", label: "Model A", description: "Balanced", default: true, reasoning_modes: modes, default_reasoning_effort: "low" },
  { id: "b", label: "Model B", description: "Deep", default: false, reasoning_modes: [modes[1]], default_reasoning_effort: "high" },
  { id: "auto", label: "Automatic model", description: "Managed by CLI", default: false, reasoning_modes: [], default_reasoning_effort: null },
];
const agent = { agent_id: "agent1", handle: "builder", harness: "codex", model: "a", reasoning_effort: "low", retired_at: null } as Agent;

beforeEach(() => { mocks.models.mockResolvedValue(catalog); mocks.update.mockResolvedValue({}); });
afterEach(() => { cleanup(); vi.clearAllMocks(); });
function mount(value = agent) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(<QueryClientProvider client={client}><AgentInference agent={value}>builder</AgentInference></QueryClientProvider>);
}

it("opens on hover and loads the agent's own provider catalog", async () => {
  mount();
  fireEvent.pointerEnter(screen.getByRole("button", { name: "Model and reasoning for builder" }));
  await screen.findByRole("combobox", { name: "Model" });
  expect(mocks.models).toHaveBeenCalledWith("agent1");
  expect(screen.getByRole("slider", { name: "Reasoning" }).getAttribute("aria-valuetext")).toBe("Low");
});

it("saves only model and reasoning and waits for server state", async () => {
  const view = mount();
  fireEvent.click(screen.getByRole("button", { name: "Model and reasoning for builder" }));
  const slider = await screen.findByRole("slider", { name: "Reasoning" });
  fireEvent.change(slider, { target: { value: "1" } });
  fireEvent.click(screen.getByRole("button", { name: "Apply" }));
  await waitFor(() => expect(mocks.update).toHaveBeenCalledWith("agent1", { model: "a", reasoning_effort: "high" }));
  expect(agent.reasoning_effort).toBe("low");
  expect((await screen.findByRole("button", { name: "Saving…" })).hasAttribute("disabled")).toBe(true);
  // A state frame acknowledges the change; the HTTP response alone does not.
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  await act(async () => view.rerender(<QueryClientProvider client={client}><AgentInference agent={{ ...agent, reasoning_effort: "high" }}>builder</AgentInference></QueryClientProvider>));
  await waitFor(() => expect(screen.queryByRole("button", { name: "Saving…" })).toBeNull());
});

it("uses the selected model's modes and hides the slider when unsupported", async () => {
  mount();
  fireEvent.click(screen.getByRole("button", { name: "Model and reasoning for builder" }));
  const picker = await screen.findByRole("combobox", { name: "Model" });
  fireEvent.change(picker, { target: { value: "b" } });
  const slider = screen.getByRole("slider", { name: "Reasoning" });
  expect(slider.getAttribute("max")).toBe("0");
  expect(slider.getAttribute("aria-valuetext")).toBe("High");
  fireEvent.change(picker, { target: { value: "auto" } });
  expect(screen.queryByRole("slider")).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Apply" }));
  await waitFor(() => expect(mocks.update).toHaveBeenCalledWith("agent1", { model: "auto", reasoning_effort: null }));
});

it("keeps failed changes editable and exposes the error", async () => {
  mocks.update.mockRejectedValue(new Error("Unsupported reasoning level"));
  mount();
  fireEvent.click(screen.getByRole("button", { name: "Model and reasoning for builder" }));
  fireEvent.change(await screen.findByRole("slider", { name: "Reasoning" }), { target: { value: "1" } });
  fireEvent.click(screen.getByRole("button", { name: "Apply" }));
  expect((await screen.findByRole("alert")).textContent).toBe("Unsupported reasoning level");
  expect(screen.getByRole("button", { name: "Apply" }).hasAttribute("disabled")).toBe(false);
});
