import { AlertTriangle, X } from "lucide-react";
import { useWorkspace } from "../store/workspace";

export function Toasts() {
  const toasts = useWorkspace((s) => s.toasts);
  const dismiss = useWorkspace((s) => s.dismissToast);
  return (
    <div className="fv-toast-region" role="status" aria-live="polite">
      {toasts.map((toast) => (
        <div key={toast.id} className="fv-toast fv-glass">
          <AlertTriangle />
          <span style={{ flex: 1 }}>{toast.message}</span>
          <button className="fv-icon-btn fv-icon-btn--sm" aria-label="Dismiss" onClick={() => dismiss(toast.id)}>
            <X />
          </button>
        </div>
      ))}
    </div>
  );
}
