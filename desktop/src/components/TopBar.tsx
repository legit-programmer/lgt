import * as DropdownMenu from "@radix-ui/react-dropdown-menu";
import { ArrowLeft, ArrowRight, Bot, Copy, Hash, Minus, PanelLeft, Plus, Square, X } from "lucide-react";
import { useEffect, useLayoutEffect, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { useUi } from "../store/ui";

/*
 * The window's top bar. It is the title bar and the app chrome in one row:
 *
 *   [sidebar toggle · back · forward · new] | [view title …] [view actions] [window controls]
 *
 * The lead zone sits over the sidebar column. Each screen fills the title and
 * actions through <TopBarSlot>, so its header code stays with the screen. Empty
 * parts of the bar drag the window (double-click maximizes). Window controls
 * appear only when the window has no native frame (Windows, see
 * src-tauri/tauri.windows.conf.json).
 */

const SLOT_IDS = { title: "topbar-title", actions: "topbar-actions" } as const;

/** Render children into the top bar's title or actions area. */
export function TopBarSlot({ target, children }: { target: keyof typeof SLOT_IDS; children: ReactNode }) {
  const [element, setElement] = useState<HTMLElement | null>(null);
  useLayoutEffect(() => setElement(document.getElementById(SLOT_IDS[target])), [target]);
  return element ? createPortal(children, element) : null;
}

type Win = Awaited<ReturnType<typeof loadWindow>>;

async function loadWindow() {
  const { getCurrentWindow } = await import("@tauri-apps/api/window");
  return getCurrentWindow();
}

function useUndecoratedWindow() {
  const [win, setWin] = useState<Win | null>(null);
  const [maximized, setMaximized] = useState(false);
  useEffect(() => {
    if (!("__TAURI_INTERNALS__" in window)) return;
    let unlisten: (() => void) | undefined;
    let live = true;
    void (async () => {
      const current = await loadWindow();
      if ((await current.isDecorated()) || !live) return;
      setWin(current);
      setMaximized(await current.isMaximized());
      unlisten = await current.onResized(async () => setMaximized(await current.isMaximized()));
    })();
    return () => {
      live = false;
      unlisten?.();
    };
  }, []);
  return { win, maximized };
}

export function TopBar({ workspace }: { workspace: boolean }) {
  const { win, maximized } = useUndecoratedWindow();
  const sidebarOpen = useUi((s) => s.sidebarOpen);
  const toggleSidebar = useUi((s) => s.toggleSidebar);
  const canBack = useUi((s) => s.historyIndex > 0);
  const canForward = useUi((s) => s.historyIndex < s.history.length - 1);
  const back = useUi((s) => s.back);
  const forward = useUi((s) => s.forward);
  const navigate = useUi((s) => s.navigate);
  const view = useUi((s) => s.view);
  const setNewChannelOpen = useUi((s) => s.setNewChannelOpen);

  return (
    <header className={`topbar${workspace && sidebarOpen ? " has-sidebar" : ""}`} data-tauri-drag-region>
      {workspace ? (
        <div className="topbar-lead" data-tauri-drag-region>
          <button className="fv-icon-btn" aria-label={sidebarOpen ? "Hide sidebar" : "Show sidebar"}
            aria-pressed={sidebarOpen} onClick={toggleSidebar}>
            <PanelLeft />
          </button>
          <button className="fv-icon-btn" aria-label="Back" disabled={!canBack} onClick={back}><ArrowLeft /></button>
          <button className="fv-icon-btn" aria-label="Forward" disabled={!canForward} onClick={forward}><ArrowRight /></button>
          <DropdownMenu.Root>
            <DropdownMenu.Trigger asChild>
              <button className="fv-icon-btn" aria-label="New channel or agent"><Plus /></button>
            </DropdownMenu.Trigger>
            <DropdownMenu.Portal>
              <DropdownMenu.Content className="fv-menu fv-glass" align="start" sideOffset={6}>
                <DropdownMenu.Item className="fv-menu-item" onSelect={() => setNewChannelOpen(true)}>
                  <Hash /> New channel
                </DropdownMenu.Item>
                <DropdownMenu.Item className="fv-menu-item" onSelect={() => navigate({ kind: "agent-new", returnTo: view })}>
                  <Bot /> New agent
                </DropdownMenu.Item>
              </DropdownMenu.Content>
            </DropdownMenu.Portal>
          </DropdownMenu.Root>
        </div>
      ) : null}
      <div className="topbar-main" data-tauri-drag-region>
        <div id={SLOT_IDS.title} className="topbar-title" data-tauri-drag-region />
        <div id={SLOT_IDS.actions} className="topbar-actions" />
      </div>
      {win ? (
        <div className="titlebar-controls">
          <button className="titlebar-button" aria-label="Minimize" onClick={() => void win.minimize()}>
            <Minus />
          </button>
          <button className="titlebar-button" aria-label={maximized ? "Restore" : "Maximize"} onClick={() => void win.toggleMaximize()}>
            {maximized ? <Copy className="titlebar-restore" /> : <Square />}
          </button>
          <button className="titlebar-button titlebar-close" aria-label="Close" onClick={() => void win.close()}>
            <X />
          </button>
        </div>
      ) : null}
    </header>
  );
}
