import { StrictMode } from "react";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  resolveBackendUrl: vi.fn(),
  backendUrl: vi.fn(() => "http://127.0.0.1:8000"),
  workspace: {
    bootError: null as string | null,
    agents: {} as Record<string, never>,
    channels: {} as Record<string, never>,
    boot: vi.fn(),
  },
  socket: { start: vi.fn(), stop: vi.fn() },
  ui: {
    view: { kind: "onboarding" as const },
    sidebarOpen: false,
    history: [] as unknown[],
    historyIndex: 0,
    toggleSidebar: vi.fn(),
    back: vi.fn(),
    forward: vi.fn(),
    navigate: vi.fn(),
    openChannel: vi.fn(),
    setPaletteOpen: vi.fn(),
    setNewChannelOpen: vi.fn(),
  },
}));

vi.mock("./api/client", () => ({
  isTauri: () => true,
  backendUrl: mocks.backendUrl,
  resolveBackendUrl: mocks.resolveBackendUrl,
}));

vi.mock("./store/workspace", () => ({
  useWorkspace: Object.assign(
    (selector: (state: typeof mocks.workspace) => unknown) => selector(mocks.workspace),
    { getState: () => mocks.workspace },
  ),
}));

vi.mock("./store/socket", () => ({ workspaceSocket: mocks.socket }));

vi.mock("./store/ui", () => ({
  useUi: Object.assign(
    (selector: (state: typeof mocks.ui) => unknown) => selector(mocks.ui),
    { getState: () => mocks.ui },
  ),
}));

vi.mock("./features/sidebar/Sidebar", () => ({ Sidebar: () => null }));
vi.mock("./features/channel/ChannelScreen", () => ({ ChannelScreen: () => null }));
vi.mock("./features/agents/AgentForm", () => ({ AgentForm: () => null }));
vi.mock("./features/onboarding/Onboarding", () => ({ Onboarding: () => <div>Ready workspace</div> }));
vi.mock("./features/palette/CommandPalette", () => ({ CommandPalette: () => null }));
vi.mock("./features/channel/NewChannelDialog", () => ({ NewChannelDialog: () => null }));
vi.mock("./components/Toasts", () => ({ Toasts: () => null }));

import { App } from "./App";

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

describe("application startup", () => {
  beforeEach(() => {
    mocks.resolveBackendUrl.mockReset().mockResolvedValue("http://127.0.0.1:8000");
    mocks.backendUrl.mockReturnValue("http://127.0.0.1:8000");
    mocks.workspace.bootError = null;
    mocks.workspace.boot.mockReset().mockResolvedValue(undefined);
    mocks.socket.start.mockReset();
    mocks.socket.stop.mockReset();
  });

  afterEach(cleanup);

  it("keeps the accessible startup overlay visible through daemon and workspace boot in StrictMode", async () => {
    const daemon = deferred<string>();
    const workspace = deferred<void>();
    mocks.resolveBackendUrl.mockReturnValueOnce(daemon.promise);
    mocks.workspace.boot.mockReturnValueOnce(workspace.promise);

    render(<StrictMode><App /></StrictMode>);

    expect(screen.getByRole("heading", { name: "Setting up your Lgt workspace" })).not.toBeNull();
    expect(screen.getByRole("status").getAttribute("aria-live")).toBe("polite");
    expect(screen.getByRole("banner")).not.toBeNull();
    expect(mocks.resolveBackendUrl).toHaveBeenCalledTimes(1);

    await act(async () => daemon.resolve("http://127.0.0.1:8000"));
    await waitFor(() => expect(mocks.workspace.boot).toHaveBeenCalledTimes(1));
    expect(screen.getByRole("status")).not.toBeNull();

    await act(async () => workspace.resolve());
    await screen.findByText("Ready workspace");
    expect(screen.queryByRole("status")).toBeNull();
    expect(mocks.socket.start).toHaveBeenCalledTimes(1);
  });

  it("shows a string startup error and restores the overlay on retry", async () => {
    const retry = deferred<string>();
    mocks.resolveBackendUrl
      .mockRejectedValueOnce("The local daemon could not start: workspace is locked")
      .mockReturnValueOnce(retry.promise);

    render(<StrictMode><App /></StrictMode>);

    expect(await screen.findByText(/The local daemon could not start: workspace is locked/)).not.toBeNull();
    expect(screen.queryByText(/uv run python/)).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));

    expect(screen.getByRole("heading", { name: "Setting up your Lgt workspace" })).not.toBeNull();
    expect(mocks.resolveBackendUrl).toHaveBeenCalledTimes(2);
    expect(screen.getByRole("banner")).not.toBeNull();

    await act(async () => retry.resolve("http://127.0.0.1:8000"));
    await screen.findByText("Ready workspace");
    expect(mocks.socket.start).toHaveBeenCalledTimes(1);
  });
});
