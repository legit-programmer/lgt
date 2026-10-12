import { renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { swipeAction, swipeDirection, useSwipe } from "./gestures";

function touch(type: string, target: EventTarget, x: number, y: number, timeStamp: number) {
  const event = new Event(type, { bubbles: true });
  const point = [{ clientX: x, clientY: y }];
  Object.defineProperties(event, {
    touches: { value: type === "touchend" ? [] : point },
    changedTouches: { value: point },
    timeStamp: { value: timeStamp },
  });
  target.dispatchEvent(event);
}

afterEach(() => { document.body.innerHTML = ""; });

describe("panel swipes", () => {
  it("recognizes quick, mostly horizontal swipes only", () => {
    expect(swipeDirection(120, 10, 200)).toBe("right");
    expect(swipeDirection(-90, -20, 300)).toBe("left");
    expect(swipeDirection(40, 0, 100)).toBeNull();
    expect(swipeDirection(100, 90, 200)).toBeNull();
    expect(swipeDirection(200, 0, 900)).toBeNull();
  });

  it("opens the near panel, or closes the far one first", () => {
    const closed = { sidebarOpen: false, detailOpen: false, hasDetail: true };
    expect(swipeAction("right", closed)).toEqual({ sidebarOpen: true });
    expect(swipeAction("left", closed)).toEqual({ detailOpen: true });
    expect(swipeAction("left", { ...closed, sidebarOpen: true })).toEqual({ sidebarOpen: false });
    expect(swipeAction("right", { ...closed, detailOpen: true })).toEqual({ detailOpen: false });
    expect(swipeAction("right", { ...closed, sidebarOpen: true })).toBeNull();
    expect(swipeAction("left", { ...closed, hasDetail: false })).toBeNull();
    // A DM keeps detailOpen from an earlier channel, but has no panel to close.
    expect(swipeAction("right", { sidebarOpen: false, detailOpen: true, hasDetail: false })).toEqual({ sidebarOpen: true });
  });

  it("ignores swipes in fields and open dialogs, and stops when disabled", () => {
    const onSwipe = vi.fn();
    const { rerender } = renderHook(({ enabled }) => useSwipe(enabled, onSwipe), { initialProps: { enabled: true } });
    const pane = document.body.appendChild(document.createElement("div"));
    touch("touchstart", pane, 20, 300, 0);
    touch("touchend", pane, 200, 310, 150);
    expect(onSwipe).toHaveBeenLastCalledWith("right");

    const field = document.body.appendChild(document.createElement("textarea"));
    touch("touchstart", field, 300, 300, 0);
    touch("touchend", field, 100, 300, 150);

    const dialog = document.body.appendChild(document.createElement("div"));
    dialog.setAttribute("role", "dialog");
    dialog.dataset.state = "open";
    touch("touchstart", pane, 300, 300, 0);
    touch("touchend", pane, 100, 300, 150);
    dialog.remove();
    expect(onSwipe).toHaveBeenCalledTimes(1);

    rerender({ enabled: false });
    touch("touchstart", pane, 300, 300, 0);
    touch("touchend", pane, 100, 300, 150);
    expect(onSwipe).toHaveBeenCalledTimes(1);
  });
});
