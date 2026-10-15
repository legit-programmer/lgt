import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const platform = vi.hoisted(() => ({ isWindowsDesktop: true }));
const win = vi.hoisted(() => ({ setEffects: vi.fn(), clearEffects: vi.fn() }));

vi.mock("./platform", () => platform);
vi.mock("@tauri-apps/api/window", () => ({
  getCurrentWindow: () => win,
  Effect: { Acrylic: "acrylic" },
}));

import { applyWindowGlass, windowGlassAvailable } from "./windowGlass";

const glass = () => document.documentElement.dataset.windowGlass;

beforeEach(() => {
  platform.isWindowsDesktop = true;
  (window as unknown as Record<string, unknown>).__TAURI_INTERNALS__ = {};
  win.setEffects.mockReset().mockResolvedValue(undefined);
  win.clearEffects.mockReset().mockResolvedValue(undefined);
});

afterEach(() => {
  delete (window as unknown as Record<string, unknown>).__TAURI_INTERNALS__;
  delete document.documentElement.dataset.windowGlass;
});

describe("window glass", () => {
  it("is only available in the Windows Tauri shell", () => {
    expect(windowGlassAvailable()).toBe(true);
    delete (window as unknown as Record<string, unknown>).__TAURI_INTERNALS__;
    expect(windowGlassAvailable()).toBe(false);
    (window as unknown as Record<string, unknown>).__TAURI_INTERNALS__ = {};
    platform.isWindowsDesktop = false;
    expect(windowGlassAvailable()).toBe(false);
  });

  it("applies Acrylic with the theme's tint, then clears the page", async () => {
    await applyWindowGlass(true, "light");
    expect(win.setEffects).toHaveBeenCalledWith({ effects: ["acrylic"], color: [245, 240, 234, 200] });
    expect(glass()).toBe("on");
  });

  it("restores the solid page when switched to opaque", async () => {
    await applyWindowGlass(true, "dark");
    await applyWindowGlass(false, "dark");
    expect(win.clearEffects).toHaveBeenCalledOnce();
    expect(glass()).toBeUndefined();
  });

  it("stays solid when Windows refuses the effect", async () => {
    win.setEffects.mockRejectedValue(new Error("unsupported"));
    await applyWindowGlass(true, "dark");
    expect(glass()).toBeUndefined();
  });

  it("never touches the window outside the Windows shell", async () => {
    platform.isWindowsDesktop = false;
    await applyWindowGlass(true, "dark");
    expect(win.setEffects).not.toHaveBeenCalled();
    expect(glass()).toBeUndefined();
  });
});
