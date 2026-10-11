import * as Dialog from "@radix-ui/react-dialog";
import { useEffect, useState, type FormEvent } from "react";
import { forgetPairedConnection, isRemoteConnection, savePairedConnection } from "../../api/client";

export function ConnectionDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (open: boolean) => void }) {
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    if (!open) { setCode(""); setError(null); }
  }, [open]);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await savePairedConnection(code);
      window.location.reload();
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "Could not connect to the workspace.");
      setBusy(false);
    }
  };

  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="fv-dialog-overlay" />
        <Dialog.Content className="fv-dialog fv-glass">
          <Dialog.Title className="fv-dialog-title">Connect to a workspace</Dialog.Title>
          <Dialog.Description className="fv-dialog-desc">
            Create a connection in Settings → Devices on the workspace computer, then paste its pairing code here.
          </Dialog.Description>
          <form onSubmit={submit} className="fv-field">
            <label htmlFor="pairing-code">Pairing code</label>
            <textarea id="pairing-code" className="fv-input" rows={5} value={code} autoFocus
              autoComplete="off" spellCheck={false} onChange={(event) => setCode(event.target.value)} />
            {error ? <p className="fv-hint" role="alert">{error}</p> : null}
            <div className="fv-dialog-actions">
              {isRemoteConnection() ? <button type="button" className="fv-btn fv-btn--ghost" disabled={busy}
                onClick={() => { forgetPairedConnection(); window.location.reload(); }}>Use local workspace</button> : null}
              <Dialog.Close asChild><button type="button" className="fv-btn fv-btn--ghost" disabled={busy}>Cancel</button></Dialog.Close>
              <button type="submit" className="fv-btn fv-btn--primary" disabled={busy || !code.trim()}>
                {busy ? "Connecting…" : "Connect"}
              </button>
            </div>
          </form>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
