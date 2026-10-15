import type { Theme } from "../store/ui";
import { isWindowsDesktop } from "./platform";

/*
 * Window glass (Windows shell only). The window is transparent and Windows
 * draws Acrylic behind it (tauri.windows.conf.json), so with the page grounds
 * cleared the sidebar, conversation and detail panels read as frosted glass
 * over the desktop.
 *
 * The blur itself is cheap; what costs GPU is the page repainting every frame,
 * because Windows then recomposites the Acrylic each time. Keep continuous
 * animations off the glass (see .fv-working-dots and .fv-status--working).
 *
 * "Opaque" clears the effect and restores the solid grounds. Browsers, mobile
 * and the other desktop platforms never have the effect.
 */

// Acrylic tint per theme, RGBA. Windows 10 applies it under the page.
const TINT: Record<Theme, [number, number, number, number]> = {
  dark: [18, 14, 12, 90],
  light: [245, 240, 234, 120],
};

let queue: Promise<void> = Promise.resolve();

/** Whether this window can show the frosted surface at all. */
export function windowGlassAvailable(): boolean {
  return isWindowsDesktop && typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;
}

function markPage(on: boolean) {
  if (on) document.documentElement.dataset.windowGlass = "on";
  else delete document.documentElement.dataset.windowGlass;
}

async function sync(frosted: boolean, theme: Theme): Promise<void> {
  if (!windowGlassAvailable()) {
    markPage(false);
    return;
  }
  try {
    const { getCurrentWindow, Effect } = await import("@tauri-apps/api/window");
    const win = getCurrentWindow();
    if (frosted) {
      // Effect first, then the transparent page, so no frame shows a bare window.
      await win.setEffects({ effects: [Effect.Acrylic], color: TINT[theme] });
      markPage(true);
    } else {
      // Solid page first, then drop the effect.
      markPage(false);
      await win.clearEffects();
    }
  } catch {
    // Windows refused the effect: stay solid.
    markPage(false);
  }
}

/** Apply the surface preference. Changes run one at a time, in order. */
export function applyWindowGlass(frosted: boolean, theme: Theme): Promise<void> {
  const run = () => sync(frosted, theme);
  queue = queue.then(run, run);
  return queue;
}
