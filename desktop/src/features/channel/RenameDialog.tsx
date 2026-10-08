import * as Dialog from "@radix-ui/react-dialog";
import { useEffect, useState, type FormEvent } from "react";
import { api } from "../../api/client";
import type { ChannelSummary } from "../../api/types";
import { reportError } from "../../store/workspace";

interface RenameDialogProps {
  channel: ChannelSummary;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function RenameDialog({ channel, open, onOpenChange }: RenameDialogProps) {
  const [name, setName] = useState(channel.name);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (open) setName(channel.name);
  }, [open, channel.name]);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (!name.trim()) return;
    setSaving(true);
    try {
      await api.renameChannel(channel.channel_id, name.trim());
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
          <Dialog.Title className="fv-dialog-title">Rename channel</Dialog.Title>
          <Dialog.Description className="fv-dialog-desc">Agents see the new name in their next turn.</Dialog.Description>
          <form onSubmit={submit} className="fv-field">
            <label htmlFor="rename-channel">Name</label>
            <input id="rename-channel" className="fv-input" value={name} autoFocus onChange={(e) => setName(e.target.value)} />
            <div className="fv-dialog-actions">
              <Dialog.Close asChild><button type="button" className="fv-btn fv-btn--ghost">Cancel</button></Dialog.Close>
              <button type="submit" className="fv-btn fv-btn--primary" disabled={saving || !name.trim()}>Rename</button>
            </div>
          </form>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
