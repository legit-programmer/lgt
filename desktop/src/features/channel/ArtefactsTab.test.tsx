import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { Artefact, ChannelSummary } from "../../api/types";
import { api } from "../../api/client";
import { useUi } from "../../store/ui";
import { useWorkspace } from "../../store/workspace";
import { ArtefactsTab } from "./ArtefactsTab";

vi.mock("../../api/client", () => ({
  api: { artefacts: vi.fn(), artefactContent: vi.fn(), artefactPreview: vi.fn(), renameArtefact: vi.fn(), deleteArtefact: vi.fn() },
  assetUrl: (path: string) => `http://localhost:8000${path}`,
  ApiError: class extends Error {},
}));
const channel = { channel_id: "c1", cwd: "/project" } as ChannelSummary;
const markdown: Artefact = { name: "plan.md", path: "plan.md", kind: "markdown", size_bytes: 20, revision: "1" };
const html: Artefact = { ...markdown, name: "chart.html", path: "chart.html", kind: "html" };
function mount() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}><ArtefactsTab channel={channel} /></QueryClientProvider>);
}
beforeEach(() => {
  vi.resetAllMocks();
  useUi.setState({ selectedArtefact: null, view: { kind: "channel", channelId: "c1" } });
  useWorkspace.setState({ artefactRevision: 0, channels: { c1: channel } });
  vi.mocked(api.artefacts).mockResolvedValue([markdown, html]);
  vi.mocked(api.artefactContent).mockResolvedValue(new Response("# A substantial plan\n\nNormal Markdown."));
  vi.mocked(api.artefactPreview).mockResolvedValue({ url: "/artefact-preview/token" });
});
afterEach(cleanup);
it("lists files from the backend and renders Markdown outside chat", async () => {
  mount();
  fireEvent.click(await screen.findByRole("button", { name: /plan.md/ }));
  expect(await screen.findByRole("heading", { name: "A substantial plan" })).toBeTruthy();
  expect(useUi.getState().sidebarOpen).toBe(false);
});
it("uses a separate sandboxed URL for HTML without workspace credentials", async () => {
  mount();
  fireEvent.click(await screen.findByRole("button", { name: /chart.html/ }));
  await waitFor(() => expect(document.querySelector("iframe")).not.toBeNull());
  const frame = document.querySelector("iframe")!;
  expect(frame.getAttribute("sandbox")).toBe("allow-scripts");
  expect(frame.getAttribute("src")).toBe("http://localhost:8000/artefact-preview/token");
  expect(frame.getAttribute("referrerpolicy")).toBe("no-referrer");
});
it("shows missing files rather than cached content", async () => {
  useUi.getState().openArtefact("c1", "/project", "gone.md");
  mount();
  expect(await screen.findByText(/no longer in this channel/)).toBeTruthy();
  expect(api.artefactContent).not.toHaveBeenCalled();
});
it("does not show a selection from a previous working directory", async () => {
  useUi.getState().openArtefact("c1", "/old-project", "plan.md");
  mount();
  expect(await screen.findByRole("button", { name: /plan.md/ })).toBeTruthy();
  expect(api.artefactContent).not.toHaveBeenCalled();
});
it("renames using the API and follows the backend rename event", async () => {
  mount();
  fireEvent.click(await screen.findByRole("button", { name: /plan.md/ }));
  fireEvent.click(await screen.findByRole("button", { name: "Rename artefact" }));
  fireEvent.change(screen.getByLabelText("Filename"), { target: { value: "next.md" } });
  fireEvent.click(screen.getByRole("button", { name: /^Rename$/ }));
  await waitFor(() => expect(api.renameArtefact).toHaveBeenCalledWith("c1", "plan.md", "next.md"));
  expect(useUi.getState().selectedArtefact?.path).toBe("plan.md");
});
