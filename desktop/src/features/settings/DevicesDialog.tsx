import * as Dialog from "@radix-ui/react-dialog";
import { CircleSlash, Smartphone } from "lucide-react";
import QRCode from "qrcode";
import { useEffect, useState, type FormEvent } from "react";
import { api } from "../../api/client";
import type { Device, DevicePairing } from "../../api/types";
import { relativeTime } from "../../lib/format";
import { reportError } from "../../store/workspace";
import "./DevicesDialog.css";

export function DevicesDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (open: boolean) => void }) {
  const [devices, setDevices] = useState<Device[] | null>(null);
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pairing, setPairing] = useState<DevicePairing | null>(null);
  const [qr, setQr] = useState<string | null>(null);

  useEffect(() => {
    let current = true;
    setPairing(null); setQr(null); setName(""); setError(null); setDevices(null);
    if (open) void api.devices().then(
      (rows) => { if (current) setDevices(rows); },
      (failure) => { if (current) setError(failure instanceof Error ? failure.message : "Could not load devices."); },
    );
    return () => { current = false; };
  }, [open]);

  useEffect(() => {
    let current = true;
    setQr(null);
    if (pairing) void QRCode.toDataURL(JSON.stringify(pairing), { width: 320, margin: 4 }).then(
      (url) => { if (current) setQr(url); }, reportError,
    );
    return () => { current = false; };
  }, [pairing]);

  const create = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true); setError(null);
    try {
      const result = await api.pairDevice(name.trim());
      setPairing(result.pairing);
      setDevices(await api.devices());
      setName("");
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "Could not create the connection.");
    } finally { setBusy(false); }
  };

  const revoke = async (device: Device) => {
    setBusy(true); setError(null);
    try {
      await api.revokeDevice(device.device_id);
      if (pairing?.device_id === device.device_id) setPairing(null);
      setDevices(await api.devices());
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "Could not revoke the connection.");
    } finally { setBusy(false); }
  };

  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="fv-dialog-overlay" />
        <Dialog.Content className="fv-dialog fv-glass">
          <Dialog.Title className="fv-dialog-title">Settings · Devices</Dialog.Title>
          <Dialog.Description className="fv-dialog-desc">
            Connect phones and other computers to this workspace. Revoking a connection disconnects it immediately.
          </Dialog.Description>
          {error ? <p className="fv-hint" role="alert">{error}</p> : null}
          {devices === null && !error ? <p role="status">Loading devices…</p> : null}
          {devices?.length === 0 ? <p className="fv-hint">No devices paired yet.</p> : null}
          <ul className="devices-list">
            {devices?.map((device) => (
              <li key={device.device_id} className="device-row">
                {device.revoked_at ? <CircleSlash aria-hidden="true" /> : <Smartphone aria-hidden="true" />}
                <div className="device-description">
                  <strong>{device.name}</strong>
                  <span className="fv-meta">{device.revoked_at ? "Revoked" : device.last_used_at
                    ? `Last connected ${relativeTime(device.last_used_at, Date.now())}` : "Not connected yet"}</span>
                </div>
                {!device.revoked_at ? <button className="fv-btn fv-btn--ghost" disabled={busy}
                  aria-label={`Revoke ${device.name}`} onClick={() => void revoke(device)}>Revoke</button> : null}
              </li>
            ))}
          </ul>
          <form onSubmit={create} className="fv-field">
            <label htmlFor="device-name">New connection name</label>
            <div className="device-create">
              <input id="device-name" className="fv-input" value={name} maxLength={100} placeholder="iPhone"
                onChange={(event) => setName(event.target.value)} />
              <button type="submit" className="fv-btn fv-btn--primary" disabled={busy || !name.trim()}>Pair device</button>
            </div>
          </form>
          {pairing ? <div className="device-pairing">
            <p>Scan to connect <strong>{pairing.name}</strong> to this workspace.</p>
            {qr ? <img src={qr} width={320} height={320} alt={`Pairing QR code for ${pairing.name}`} /> : null}
            <p className="fv-hint">This code grants workspace access until you revoke the connection. It is shown only here.</p>
            <button type="button" className="fv-btn" onClick={() => {
              void navigator.clipboard.writeText(JSON.stringify(pairing)).catch(reportError);
            }}>Copy pairing code</button>
          </div> : null}
          <div className="fv-dialog-actions">
            <Dialog.Close asChild><button className="fv-btn fv-btn--ghost">Close</button></Dialog.Close>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
