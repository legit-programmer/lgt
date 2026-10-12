import { useSyncExternalStore } from "react";

/*
 * Pairing QR scanning on mobile. The camera preview runs behind a transparent
 * webview (`windowed: true`), so the app draws its own frame and Cancel button
 * (components/ScanOverlay.tsx). Android shows no native cancel control, so the
 * overlay and the back button both call cancelScan().
 */

let active = false;
const listeners = new Set<() => void>();

function setActive(value: boolean) {
  active = value;
  document.documentElement.classList.toggle("is-scanning", value);
  listeners.forEach((listener) => listener());
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function isScanning(): boolean {
  return active;
}

export function useScanning(): boolean {
  return useSyncExternalStore(subscribe, isScanning);
}

/** Scan a QR code with the back camera. Resolves null when the scan is cancelled. */
export async function scanQrCode(): Promise<string | null> {
  const scanner = await import("@tauri-apps/plugin-barcode-scanner");
  let permission = await scanner.checkPermissions();
  if (permission !== "granted") permission = await scanner.requestPermissions();
  if (permission !== "granted") {
    throw new Error("Allow camera access for Lgt in the system settings to scan the pairing code.");
  }
  setActive(true);
  try {
    const result = await scanner.scan({ windowed: true, formats: [scanner.Format.QRCode] });
    return result.content;
  } catch (error) {
    if (String(error).toLowerCase().includes("cancel")) return null;
    throw error;
  } finally {
    setActive(false);
  }
}

export async function cancelScan(): Promise<void> {
  if (!active) return;
  const { cancel } = await import("@tauri-apps/plugin-barcode-scanner");
  await cancel();
}
