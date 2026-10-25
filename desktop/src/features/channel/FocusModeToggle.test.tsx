import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Channel } from "../../api/types";
import { FocusModeToggle } from "./FocusModeToggle";

const mocks = vi.hoisted(() => ({ setFocusMode: vi.fn(), reportError: vi.fn() }));
vi.mock("../../api/client", () => ({ api: { setFocusMode: mocks.setFocusMode } }));
vi.mock("../../store/workspace", () => ({ reportError: mocks.reportError }));
afterEach(() => { cleanup(); vi.resetAllMocks(); });

describe("focus mode", () => {
  it.each(["channel", "dm"] as const)("waits for server state when switching a %s", async (kind) => {
    const channel = { channel_id: "c", focus_mode: false, kind } as Channel;
    mocks.setFocusMode.mockResolvedValue({ ...channel, focus_mode: true });
    const view = render(<FocusModeToggle channel={channel} />);
    const button = screen.getByRole("button", { name: "Focus mode" });
    expect(button.getAttribute("aria-pressed")).toBe("false");
    fireEvent.click(button);
    await waitFor(() => expect(mocks.setFocusMode).toHaveBeenCalledWith("c", true));
    expect(button.getAttribute("aria-pressed")).toBe("false");
    view.rerender(<FocusModeToggle channel={{ ...channel, focus_mode: true }} />);
    expect(button.getAttribute("aria-pressed")).toBe("true");
    await waitFor(() => expect(button.hasAttribute("disabled")).toBe(false));
    fireEvent.click(button);
    await waitFor(() => expect(mocks.setFocusMode).toHaveBeenLastCalledWith("c", false));
  });

  it("keeps the saved mode after a failed change and reports the error", async () => {
    const error = new Error("Connection lost");
    mocks.setFocusMode.mockRejectedValue(error);
    render(<FocusModeToggle channel={{ channel_id: "c", focus_mode: true } as Channel} />);
    const button = screen.getByRole("button", { name: "Focus mode" });
    fireEvent.click(button);
    await waitFor(() => expect(mocks.reportError).toHaveBeenCalledWith(error));
    expect(button.getAttribute("aria-pressed")).toBe("true");
    expect(button.hasAttribute("disabled")).toBe(false);
  });
});
