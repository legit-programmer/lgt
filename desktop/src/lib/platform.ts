import { useEffect, useState } from "react";

/*
 * The Tauri CLI exports TAURI_ENV_PLATFORM to the frontend build, so mobile is
 * known at build time. A plain browser build leaves it unset.
 */
const platform = import.meta.env.TAURI_ENV_PLATFORM as string | undefined;

/** A paired phone client: no local workspace, no window chrome. */
export const isMobile = platform === "android" || platform === "ios";
export const isAndroid = platform === "android";
export const isIos = platform === "ios";

const COMPACT_QUERY = "(max-width: 760px)";
/** A phone-width touch screen: panels open by swiping instead of top bar toggles (lib/gestures.ts). */
const TOUCH_PANELS_QUERY = "(max-width: 760px) and (pointer: coarse)";

function matches(query: string): boolean {
  return typeof window !== "undefined" && typeof window.matchMedia === "function"
    && window.matchMedia(query).matches;
}

function useMediaQuery(query: string): boolean {
  const [state, setState] = useState(() => matches(query));
  useEffect(() => {
    if (typeof window.matchMedia !== "function") return;
    const list = window.matchMedia(query);
    const update = () => setState(list.matches);
    update();
    list.addEventListener("change", update);
    return () => list.removeEventListener("change", update);
  }, [query]);
  return state;
}

/** Phone-width layout: the sidebar and detail panel overlay the conversation. */
export function useCompactLayout(): boolean {
  return useMediaQuery(COMPACT_QUERY);
}

/** Phone-width touch layout: swipes open and close the panels. */
export function useTouchPanels(): boolean {
  return useMediaQuery(TOUCH_PANELS_QUERY);
}
