import * as Dialog from "@radix-ui/react-dialog";
import { ScanLine } from "lucide-react";
import { useEffect, useState, type FormEvent } from "react";
import { forgetPairedConnection, isRemoteConnection, savePairedConnection } from "../../api/client";
import { isMobile } from "../../lib/platform";
import { scanQrCode } from "../../lib/scan";

export function ConnectionDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (open: boolean) => void }) {
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    if (!open) { setCode(""); setError(null); }
  }, [open]);

  const connect = async (raw: string) => {
    setBusy(true);
    setError(null);
    try {
      await savePairedConnection(raw);
      window.location.reload();
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "Could not connect to the workspace.");
      setBusy(false);
    }
  };

  const submit = (event: FormEvent) => {
    event.preventDefault();
    void connect(code);
  };

  const scan = async () => {
    setError(null);
    try {
      const scanned = await scanQrCode();
      if (scanned === null) return;
      setCode(scanned);
      await connect(scanned);
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : String(failure));
    }
  };

  // A phone has no local workspace to fall back to, so leaving a pairing disconnects.
  const leaveLabel = isMobile ? "Disconnect" : "Use local workspace";

  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="fv-dialog-overlay" />
        <Dialog.Content className="fv-dialog fv-glass">
          <Dialog.Title className="fv-dialog-title">Connect to a workspace</Dialog.Title>
          <Dialog.Description className="fv-dialog-desc">
            {isMobile
              ? "Create a connection in Settings → Devices on the workspace computer, then scan its QR code or paste its pairing code here."
              : "Create a connection in Settings → Devices on the workspace computer, then paste its pairing code here."}
          </Dialog.Description>
          {isMobile ? (
            <button type="button" className="fv-btn fv-btn--primary connection-scan" disabled={busy} onClick={() => void scan()}>
              <ScanLine /> Scan QR code
            </button>
          ) : null}
          <form onSubmit={submit} className="fv-field">
            <label htmlFor="pairing-code">Pairing code</label>
            <textarea id="pairing-code" className="fv-input" rows={5} value={code} autoFocus={!isMobile}
              autoComplete="off" spellCheck={false} onChange={(event) => setCode(event.target.value)} />
            {error ? <p className="fv-hint" role="alert">{error}</p> : null}
            <div className="fv-dialog-actions">
              {isRemoteConnection() ? <button type="button" className="fv-btn fv-btn--ghost" disabled={busy}
                onClick={() => { forgetPairedConnection(); window.location.reload(); }}>{leaveLabel}</button> : null}
              <Dialog.Close asChild><button type="button" className="fv-btn fv-btn--ghost" disabled={busy}>Cancel</button></Dialog.Close>
              <button type="submit" className={`fv-btn ${isMobile ? "fv-btn--ghost" : "fv-btn--primary"}`} disabled={busy || !code.trim()}>
                {busy ? "Connecting…" : "Connect"}
              </button>
            </div>
          </form>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
