import { afterEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({ setConnection: vi.fn(), toast: vi.fn(), refreshSummaries: vi.fn() }));
vi.mock("../api/client", () => ({ socketUrl: () => "wss://lgt.example/ws", socketHandshake: () => ({ last_id: 0, token: "device" }) }));
vi.mock("./workspace", () => ({ useWorkspace: { getState: () => ({ ...mocks, lastEventId: 0 }) } }));

class FakeSocket {
  static OPEN = 1;
  static sockets: FakeSocket[] = [];
  onclose: ((event: { code: number; reason: string }) => void) | null = null;
  close() { /* tests deliver close events explicitly */ }
  constructor() { FakeSocket.sockets.push(this); }
}

afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); vi.clearAllMocks(); FakeSocket.sockets = []; });

describe("socket policy failures", () => {
  it("stops retries on revocation while ignoring close events from a replaced socket", async () => {
    vi.useFakeTimers();
    vi.stubGlobal("WebSocket", FakeSocket);
    const { workspaceSocket } = await import("./socket");
    workspaceSocket.start();
    const old = FakeSocket.sockets[0];
    workspaceSocket.stop();
    workspaceSocket.start();
    const current = FakeSocket.sockets[1];
    old.onclose?.({ code: 1008, reason: "Old connection" });
    expect(mocks.toast).not.toHaveBeenCalled();
    current.onclose?.({ code: 1008, reason: "Device credential revoked." });
    expect(mocks.setConnection).toHaveBeenLastCalledWith("unreachable");
    expect(mocks.toast).toHaveBeenCalledWith("Device credential revoked.");
    await vi.advanceTimersByTimeAsync(30000);
    expect(FakeSocket.sockets).toHaveLength(2);
    expect(mocks.refreshSummaries).not.toHaveBeenCalled();
    workspaceSocket.stop();
  });
});
