/*
 * Window glass: in the Tauri shell the window is transparent and the OS blurs
 * whatever sits behind it (acrylic on Windows, vibrancy on macOS). The side
 * panels then render as frosted glass over the desktop. A plain browser has no
 * such effect, so the page keeps its solid surfaces there.
 */

type Theme = "dark" | "light";

// Acrylic tint per theme. Windows 10 applies it; Windows 11 ignores the colour.
const TINT: Record<Theme, [number, number, number, number]> = {
  dark: [18, 14, 12, 120],
  light: [245, 240, 234, 120],
};

function inTauri(): boolean {
  return typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;
}

export async function applyWindowGlass(theme: Theme): Promise<void> {
  const root = document.documentElement;
  if (!inTauri()) {
    delete root.dataset.windowGlass;
    return;
  }
  try {
    const { getCurrentWindow, Effect } = await import("@tauri-apps/api/window");
    await getCurrentWindow().setEffects({
      effects: [Effect.Acrylic, Effect.UnderWindowBackground],
      color: TINT[theme],
    });
    root.dataset.windowGlass = "on";
  } catch {
    // The platform refused the effect (Linux, or an older Windows): stay solid.
    delete root.dataset.windowGlass;
  }
}
