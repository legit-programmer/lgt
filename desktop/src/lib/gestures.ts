import { useEffect, useRef } from "react";
import { isScanning } from "./scan";

/*
 * Phone panel gestures: swiping right reveals the sidebar on the left, swiping
 * left reveals the detail panel on the right, and the opposite swipe closes
 * whichever is open. They replace the top bar's panel toggles on touch phones.
 */

export type Swipe = "left" | "right";

const MIN_DISTANCE = 60;
const MAX_DURATION_MS = 600;
/** Horizontal travel must clearly dominate, so vertical scrolling never opens a panel. */
const DOMINANCE = 1.5;

export function swipeDirection(dx: number, dy: number, durationMs: number): Swipe | null {
  if (durationMs > MAX_DURATION_MS || Math.abs(dx) < MIN_DISTANCE || Math.abs(dx) < Math.abs(dy) * DOMINANCE) {
    return null;
  }
  return dx > 0 ? "right" : "left";
}

export interface PanelState {
  sidebarOpen: boolean;
  detailOpen: boolean;
  /** Whether the current view has a detail panel (channels do, DMs don't). */
  hasDetail: boolean;
}

export type PanelChange = { sidebarOpen: boolean } | { detailOpen: boolean } | null;

/** One swipe changes one panel: close the panel on the far side first, otherwise open the near one. */
export function swipeAction(swipe: Swipe, state: PanelState): PanelChange {
  const detailShown = state.hasDetail && state.detailOpen;
  if (swipe === "right") {
    if (detailShown) return { detailOpen: false };
    return state.sidebarOpen ? null : { sidebarOpen: true };
  }
  if (state.sidebarOpen) return { sidebarOpen: false };
  return state.hasDetail && !state.detailOpen ? { detailOpen: true } : null;
}

/** Touches that belong to something else: dialogs, menus, the scanner, fields, and horizontal scrollers. */
function swipeBlockedAt(target: EventTarget | null): boolean {
  if (isScanning() || document.querySelector("[role=dialog][data-state=open], [role=menu][data-state=open]")) {
    return true;
  }
  for (let el = target instanceof Element ? target : null; el && el !== document.body; el = el.parentElement) {
    if (el.matches("input, textarea, select, [contenteditable=true]")) return true;
    if (el.scrollWidth > el.clientWidth + 1 && /auto|scroll/.test(getComputedStyle(el).overflowX)) return true;
  }
  return false;
}

export function useSwipe(enabled: boolean, onSwipe: (swipe: Swipe) => void) {
  const handler = useRef(onSwipe);
  handler.current = onSwipe;
  useEffect(() => {
    if (!enabled) return;
    let start: { x: number; y: number; t: number } | null = null;
    const down = (event: TouchEvent) => {
      const touch = event.touches[0];
      start = event.touches.length === 1 && !swipeBlockedAt(event.target)
        ? { x: touch.clientX, y: touch.clientY, t: event.timeStamp }
        : null;
    };
    const up = (event: TouchEvent) => {
      if (!start) return;
      const touch = event.changedTouches[0];
      const swipe = swipeDirection(touch.clientX - start.x, touch.clientY - start.y, event.timeStamp - start.t);
      start = null;
      // A drag that selected text is a selection (for quoting), not a swipe.
      if (swipe && window.getSelection()?.isCollapsed !== false) handler.current(swipe);
    };
    const cancel = () => { start = null; };
    document.addEventListener("touchstart", down, { passive: true });
    document.addEventListener("touchend", up, { passive: true });
    document.addEventListener("touchcancel", cancel, { passive: true });
    return () => {
      document.removeEventListener("touchstart", down);
      document.removeEventListener("touchend", up);
      document.removeEventListener("touchcancel", cancel);
    };
  }, [enabled]);
}
