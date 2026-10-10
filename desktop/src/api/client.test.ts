import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const invoke = vi.hoisted(() => vi.fn());
vi.mock("@tauri-apps/api/core", () => ({ invoke }));

beforeEach(() => {
  vi.resetModules();
  invoke.mockReset();
  Object.defineProperty(window, "__TAURI_INTERNALS__", { value: {}, configurable: true });
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("{}", {
    headers: { "Content-Type": "application/json" },
  })));
});

afterEach(() => {
  Reflect.deleteProperty(window, "__TAURI_INTERNALS__");
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
});

describe("daemon connection", () => {
  it("shares a concurrent launch and retries failed discovery", async () => {
    invoke.mockRejectedValueOnce("Backend startup failed");
    const client = await import("./client");
    const first = client.resolveBackendUrl();
    expect(client.resolveBackendUrl()).toBe(first);
    await expect(first).rejects.toBe("Backend startup failed");
    expect(invoke).toHaveBeenCalledOnce();
    invoke.mockResolvedValue({ url: "http://127.0.0.1:43210", token: "launch-secret", managed: true });
    await expect(client.resolveBackendUrl()).resolves.toBe("http://127.0.0.1:43210");
    expect(invoke).toHaveBeenLastCalledWith("ensure_backend");
  });

  it("authenticates API, media, and the first WebSocket frame without URL credentials", async () => {
    invoke.mockResolvedValue({ url: "http://127.0.0.1:43210", token: "launch-secret", managed: true });
    const client = await import("./client");
    await client.resolveBackendUrl();
    await client.api.me();
    await client.fetchBackendResource(client.api.thumbnailUrl("image"), { mode: "cors" });
    for (const [url, init] of vi.mocked(fetch).mock.calls) {
      expect(String(url)).not.toContain("launch-secret");
      expect(new Headers(init?.headers).get("Authorization")).toBe("Bearer launch-secret");
      expect(init?.redirect).toBe("error");
    }
    expect(client.socketUrl()).toBe("ws://127.0.0.1:43210/ws");
    expect(client.socketHandshake(12)).toEqual({ last_id: 12, token: "launch-secret" });
    await expect(client.fetchBackendResource("https://example.com/image")).rejects.toThrow("outside");
    expect(fetch).toHaveBeenCalledTimes(2);
  });

  it("refreshes the token and address when retry discovers a restarted daemon", async () => {
    invoke.mockResolvedValueOnce({ url: "http://127.0.0.1:43210", token: "old", managed: true })
      .mockResolvedValueOnce({ url: "http://127.0.0.1:43211", token: "new", managed: true });
    const client = await import("./client");
    await client.resolveBackendUrl();
    await client.resolveBackendUrl();
    expect(client.backendUrl()).toBe("http://127.0.0.1:43211");
    expect(client.socketHandshake(0).token).toBe("new");
  });

  it("keeps browser development compatible with a manually started backend", async () => {
    Reflect.deleteProperty(window, "__TAURI_INTERNALS__");
    vi.stubEnv("VITE_LGT_BACKEND_URL", "http://127.0.0.1:8001/");
    const client = await import("./client");
    await client.resolveBackendUrl();
    await client.api.me();
    expect(invoke).not.toHaveBeenCalled();
    expect(client.backendUrl()).toBe("http://127.0.0.1:8001");
    expect(client.socketHandshake(3)).toEqual({ last_id: 3 });
    expect(new Headers(vi.mocked(fetch).mock.calls[0][1]?.headers).has("Authorization")).toBe(false);
  });
});
