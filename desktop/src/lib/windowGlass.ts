/*
 * Window glass: in the Tauri shell the window is transparent and the OS blurs
 * whatever sits behind it (blur on Windows, vibrancy on macOS). The side panels
 * then render as frosted glass over the desktop.
 *
 * The blur is recomposited by the OS on every frame, so it is only applied while
 * Lgt has focus. Unfocused, the page switches to its solid surfaces and the
 * effect is cleared, which costs nothing behind a game or a video. A plain
 * browser never has the effect and always stays solid.
 */

type Theme = "dark" | "light";

// Blur tint per theme. Windows 10 applies it; Windows 11 ignores the colour.
const TINT: Record<Theme, [number, number, number, number]> = {
  dark: [18, 14, 12, 120],
  light: [245, 240, 234, 120],
};

let theme: Theme = "dark";
let focused = true;
let listening = false;
let queue: Promise<void> = Promise.resolve();

function inTauri(): boolean {
  return typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;
}

function setGlassAttribute(on: boolean) {
  if (on) document.documentElement.dataset.windowGlass = "on";
  else delete document.documentElement.dataset.windowGlass;
}

async function sync(): Promise<void> {
  if (!inTauri()) {
    setGlassAttribute(false);
    return;
  }
  try {
    const { getCurrentWindow, Effect } = await import("@tauri-apps/api/window");
    const win = getCurrentWindow();
    if (!listening) {
      listening = true;
      focused = await win.isFocused();
      await win.onFocusChanged(({ payload }) => {
        focused = payload;
        schedule();
      });
    }
    if (focused) {
      // Effect first, then the transparent page, so no frame shows a bare window.
      await win.setEffects({ effects: [Effect.Blur, Effect.UnderWindowBackground], color: TINT[theme] });
      setGlassAttribute(true);
    } else {
      // Solid page first, then drop the effect.
      setGlassAttribute(false);
      await win.clearEffects();
    }
  } catch {
    // The platform refused the effect (Linux, or an older Windows): stay solid.
    setGlassAttribute(false);
  }
}

// Effect changes are applied one at a time, in order.
function schedule(): Promise<void> {
  queue = queue.then(sync, sync);
  return queue;
}

export function applyWindowGlass(next: Theme): Promise<void> {
  theme = next;
  return schedule();
}
