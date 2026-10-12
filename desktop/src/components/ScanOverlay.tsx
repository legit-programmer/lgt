import { X } from "lucide-react";
import { createPortal } from "react-dom";
import { cancelScan, useScanning } from "../lib/scan";

/**
 * Drawn over the camera preview while a pairing QR scan runs. The rest of the
 * page is hidden and transparent (html.is-scanning), so only this shows.
 */
export function ScanOverlay() {
  const scanning = useScanning();
  if (!scanning) return null;
  return createPortal(
    <div className="scan-overlay" role="dialog" aria-modal="true" aria-label="Scan pairing code">
      <div className="scan-frame" aria-hidden="true" />
      <p className="scan-hint">Point the camera at the QR code in Settings → Devices on the workspace computer.</p>
      <button type="button" className="fv-btn scan-cancel" onClick={() => void cancelScan()}>
        <X /> Cancel
      </button>
    </div>,
    document.body,
  );
}
