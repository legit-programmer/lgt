import { socketHandshake, socketUrl } from "../api/client";
import type { ClientCommand, ServerFrame } from "../api/types";
import { useWorkspace } from "./workspace";

/**
 * One WebSocket per window. The first frame is the replay cursor; the server
 * replays durable events after it, then sends state snapshots. A `resync`
 * frame or a 1013 close means the live buffer overflowed: summaries and open
 * timelines are reloaded over HTTP and the socket reconnects from the cursor.
 */
class WorkspaceSocket {
  private socket: WebSocket | null = null;
  private retry = 0;
  private timer: number | null = null;
  private stopped = false;

  start() {
    this.stopped = false;
    this.connect();
  }

  stop() {
    this.stopped = true;
    if (this.timer !== null) window.clearTimeout(this.timer);
    this.socket?.close();
    this.socket = null;
  }

  send(command: ClientCommand): boolean {
    if (this.socket?.readyState !== WebSocket.OPEN) return false;
    this.socket.send(JSON.stringify(command));
    return true;
  }

  private connect() {
    const store = useWorkspace.getState();
    store.setConnection(this.retry === 0 ? "connecting" : "reconnecting");
    let socket: WebSocket;
    try {
      socket = new WebSocket(socketUrl());
    } catch {
      this.schedule();
      return;
    }
    this.socket = socket;
    socket.onopen = () => {
      socket.send(JSON.stringify(socketHandshake(useWorkspace.getState().lastEventId)));
      this.retry = 0;
      useWorkspace.getState().setConnection("open");
    };
    socket.onmessage = (message) => {
      let frame: ServerFrame;
      try {
        frame = JSON.parse(message.data as string) as ServerFrame;
      } catch {
        return;
      }
      useWorkspace.getState().applyFrame(frame);
    };
    socket.onclose = () => {
      if (this.socket === socket) this.socket = null;
      if (!this.stopped) this.schedule();
    };
  }

  private schedule() {
    this.retry += 1;
    const delay = Math.min(15000, 500 * 2 ** Math.min(this.retry, 5));
    useWorkspace.getState().setConnection(this.retry > 3 ? "unreachable" : "reconnecting");
    this.timer = window.setTimeout(() => {
      this.timer = null;
      // A reconnect after a gap also refreshes summaries the cursor cannot replay.
      void useWorkspace.getState().refreshSummaries();
      this.connect();
    }, delay);
  }
}

export const workspaceSocket = new WorkspaceSocket();
