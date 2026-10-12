import * as Dialog from "@radix-ui/react-dialog";
import { useEffect, useState, useSyncExternalStore, type FormEvent } from "react";

/*
 * Asks for a directory path on the workspace host when no native folder dialog
 * applies (a remote workspace, a phone, or a plain browser). window.prompt is
 * not reliably available in mobile webviews, so this is an app dialog.
 */

interface PathRequest {
  title: string;
  defaultPath: string;
  resolve(value: string | null): void;
}

let current: PathRequest | null = null;
const listeners = new Set<() => void>();

function publish(request: PathRequest | null) {
  current = request;
  listeners.forEach((listener) => listener());
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

/** Resolves the typed absolute path, or null when cancelled. */
export function requestPath(title: string, defaultPath?: string | null): Promise<string | null> {
  current?.resolve(null);
  return new Promise((resolve) => publish({ title, defaultPath: defaultPath ?? "", resolve }));
}

export function PathPromptHost() {
  const request = useSyncExternalStore(subscribe, () => current);
  const [value, setValue] = useState("");
  useEffect(() => {
    if (request) setValue(request.defaultPath);
  }, [request]);

  const finish = (result: string | null) => {
    request?.resolve(result);
    publish(null);
  };

  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (value.trim()) finish(value.trim());
  };

  return (
    <Dialog.Root open={request !== null} onOpenChange={(open) => { if (!open) finish(null); }}>
      <Dialog.Portal>
        <Dialog.Overlay className="fv-dialog-overlay" />
        <Dialog.Content className="fv-dialog fv-glass">
          <Dialog.Title className="fv-dialog-title">{request?.title}</Dialog.Title>
          <Dialog.Description className="fv-dialog-desc">
            Enter an absolute directory path on the workspace computer.
          </Dialog.Description>
          <form onSubmit={submit} className="fv-field">
            <label htmlFor="workspace-path">Directory</label>
            <input id="workspace-path" className="fv-input fv-mono" value={value} autoFocus
              autoCapitalize="off" autoCorrect="off" autoComplete="off" spellCheck={false}
              onChange={(event) => setValue(event.target.value)} />
            <div className="fv-dialog-actions">
              <Dialog.Close asChild><button type="button" className="fv-btn fv-btn--ghost">Cancel</button></Dialog.Close>
              <button type="submit" className="fv-btn fv-btn--primary" disabled={!value.trim()}>Use directory</button>
            </div>
          </form>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
