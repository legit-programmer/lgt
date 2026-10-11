import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Device } from "../../api/types";

const mocks = vi.hoisted(() => ({ devices: vi.fn(), pairDevice: vi.fn(), revokeDevice: vi.fn() }));
vi.mock("../../api/client", () => ({ api: mocks }));
vi.mock("../../store/workspace", () => ({ reportError: vi.fn() }));
vi.mock("qrcode", () => ({ default: { toDataURL: vi.fn().mockResolvedValue("data:image/png;base64,code") } }));
import { DevicesDialog } from "./DevicesDialog";

afterEach(() => { cleanup(); vi.clearAllMocks(); });

describe("device settings", () => {
  it("shows a newly generated pairing once and reflects server revocation before removing access controls", async () => {
    const device: Device = { device_id: "phone", name: "iPhone", created_at: "2026-10-12T00:00:00Z", last_used_at: null, revoked_at: null };
    const pairing = { type: "lgt-device", version: 1, url: "https://lgt.example", device_id: "phone", name: "iPhone", token: "secret" };
    mocks.devices.mockResolvedValueOnce([]).mockResolvedValueOnce([device]);
    mocks.pairDevice.mockResolvedValue({ device, pairing });
    const view = render(<DevicesDialog open onOpenChange={() => {}} />);
    await screen.findByText("No devices paired yet.");
    fireEvent.change(screen.getByLabelText("New connection name"), { target: { value: "iPhone" } });
    fireEvent.click(screen.getByRole("button", { name: "Pair device" }));
    await screen.findByRole("img", { name: "Pairing QR code for iPhone" });
    expect(mocks.pairDevice).toHaveBeenCalledWith("iPhone");
    expect(screen.getByText("Not connected yet")).not.toBeNull();
    let complete!: () => void;
    mocks.revokeDevice.mockReturnValue(new Promise<void>((resolve) => { complete = resolve; }));
    mocks.devices.mockResolvedValueOnce([{ ...device, revoked_at: "2026-10-12T01:00:00Z" }]);
    fireEvent.click(screen.getByRole("button", { name: "Revoke iPhone" }));
    expect(screen.queryByText("Revoked")).toBeNull();
    await act(async () => complete());
    await screen.findByText("Revoked");
    expect(screen.queryByRole("button", { name: "Revoke iPhone" })).toBeNull();
    expect(screen.queryByRole("img")).toBeNull();
    view.rerender(<DevicesDialog open={false} onOpenChange={() => {}} />);
    mocks.devices.mockResolvedValueOnce([device]);
    view.rerender(<DevicesDialog open onOpenChange={() => {}} />);
    await waitFor(() => expect(screen.queryByRole("img")).toBeNull());
    expect(screen.queryByRole("button", { name: "Copy pairing code" })).toBeNull();
  });

  it("shows configuration errors when pairing is unavailable", async () => {
    mocks.devices.mockResolvedValue([]);
    mocks.pairDevice.mockRejectedValue(new Error("Configure listen_host and advertised_url before pairing."));
    render(<DevicesDialog open onOpenChange={() => {}} />);
    await screen.findByText("No devices paired yet.");
    fireEvent.change(screen.getByLabelText("New connection name"), { target: { value: "iPhone" } });
    fireEvent.click(screen.getByRole("button", { name: "Pair device" }));
    expect(await screen.findByRole("alert")).not.toBeNull();
    expect(screen.queryByRole("img")).toBeNull();
  });
});
