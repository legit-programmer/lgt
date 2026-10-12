import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const invoke = vi.hoisted(() => vi.fn());
vi.mock("@tauri-apps/api/core", () => ({ invoke }));

beforeEach(() => {
  localStorage.clear();
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
  const pairing = { type: "lgt-device", version: 1, url: "https://lgt.example", device_id: "phone",
    name: "iPhone", token: "lgt_device_" + "a".repeat(43) };

  it("verifies and persists pairing, reuses it after reload, and bypasses local daemon discovery", async () => {
    vi.mocked(fetch).mockResolvedValueOnce(new Response(JSON.stringify({ device_id: "phone", local_admin: false })));
    let client = await import("./client");
    await client.savePairedConnection(JSON.stringify(pairing));
    expect(new Headers(vi.mocked(fetch).mock.calls[0][1]?.headers).get("Authorization")).toBe(`Bearer ${pairing.token}`);
    expect(vi.mocked(fetch).mock.calls[0][1]?.redirect).toBe("error");
    vi.resetModules();
    client = await import("./client");
    expect(await client.resolveBackendUrl()).toBe(pairing.url);
    expect(client.socketHandshake(3)).toEqual({ last_id: 3, token: pairing.token });
    await client.api.me();
    expect(new Headers(vi.mocked(fetch).mock.calls[1][1]?.headers).get("Authorization")).toBe(`Bearer ${pairing.token}`);
    expect(invoke).not.toHaveBeenCalled();
    expect(client.isRemoteConnection()).toBe(true);
    await client.quitWorkspace();
    expect(invoke).toHaveBeenCalledWith("quit_client");
    await expect(client.fetchBackendResource("https://other.example/attachment")).rejects.toThrow("outside");
    client.forgetPairedConnection();
    vi.resetModules();
    client = await import("./client");
    invoke.mockResolvedValue({ url: "http://127.0.0.1:1234", token: "local", managed: true });
    await client.resolveBackendUrl();
    expect(invoke).toHaveBeenLastCalledWith("ensure_backend");
    expect(client.isRemoteConnection()).toBe(false);
  });

  it("does not replace a saved pairing when a new credential is rejected", async () => {
    localStorage.setItem("lgt.pairedConnection", JSON.stringify(pairing));
    vi.mocked(fetch).mockResolvedValueOnce(new Response("{}", { status: 401 }));
    const client = await import("./client");
    await expect(client.savePairedConnection(JSON.stringify({ ...pairing, token: "lgt_device_" + "b".repeat(43) })))
      .rejects.toThrow("rejected");
    expect(JSON.parse(localStorage.getItem("lgt.pairedConnection")!).token).toBe(pairing.token);
  });

  it("rejects malformed pairing URLs and mismatched device identities before storing a credential", async () => {
    const client = await import("./client");
    for (const url of ["javascript:alert(1)", "https://user:secret@host", "https://host/path", "https://host?token=secret", "http://0.0.0.0:8000", "http://host:0"]) {
      await expect(client.savePairedConnection(JSON.stringify({ ...pairing, url }))).rejects.toThrow();
    }
    expect(fetch).not.toHaveBeenCalled();
    vi.mocked(fetch).mockResolvedValueOnce(new Response(JSON.stringify({ device_id: "other", local_admin: false })));
    await expect(client.savePairedConnection(JSON.stringify(pairing))).rejects.toThrow("recognize");
    expect(localStorage.getItem("lgt.pairedConnection")).toBeNull();
  });

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

  it("asks a phone to pair instead of discovering a local daemon, then uses its pairing", async () => {
    vi.stubEnv("TAURI_ENV_PLATFORM", "android");
    let client = await import("./client");
    await expect(client.resolveBackendUrl()).rejects.toBeInstanceOf(client.PairingRequiredError);
    expect(invoke).not.toHaveBeenCalled();
    localStorage.setItem("lgt.pairedConnection", JSON.stringify({ type: "lgt-device", version: 1,
      url: "https://lgt.example", device_id: "phone", name: "Pixel", token: "lgt_device_" + "a".repeat(43) }));
    vi.resetModules();
    client = await import("./client");
    expect(await client.resolveBackendUrl()).toBe("https://lgt.example");
    expect(client.isRemoteConnection()).toBe(true);
    expect(invoke).not.toHaveBeenCalled();
  });
});
