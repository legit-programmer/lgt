import * as Dialog from "@radix-ui/react-dialog";
import { useEffect, useState, type FormEvent } from "react";
import { api } from "../../api/client";
import { reportError, useWorkspace } from "../../store/workspace";

export function ProfileDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (open: boolean) => void }) {
  const me = useWorkspace((s) => s.me);
  const [name, setName] = useState(me?.display_name ?? "");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (open) setName(me?.display_name ?? "");
  }, [open, me?.display_name]);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    const trimmed = name.trim();
    if (!trimmed) return;
    setSaving(true);
    try {
      const profile = await api.updateMe(trimmed);
      useWorkspace.setState({ me: profile });
      onOpenChange(false);
    } catch (error) {
      reportError(error);
    } finally {
      setSaving(false);
    }
  };

  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="fv-dialog-overlay" />
        <Dialog.Content className="fv-dialog fv-glass">
          <Dialog.Title className="fv-dialog-title">Your name</Dialog.Title>
          <Dialog.Description className="fv-dialog-desc">Shown on your messages in every conversation.</Dialog.Description>
          <form onSubmit={submit} className="fv-field">
            <label htmlFor="display-name">Display name</label>
            <input id="display-name" className="fv-input" value={name} maxLength={100} autoFocus
              onChange={(e) => setName(e.target.value)} />
            <div className="fv-dialog-actions">
              <Dialog.Close asChild><button type="button" className="fv-btn fv-btn--ghost">Cancel</button></Dialog.Close>
              <button type="submit" className="fv-btn fv-btn--primary" disabled={saving || !name.trim()}>Save</button>
            </div>
          </form>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
