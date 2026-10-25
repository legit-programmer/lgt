import { Focus } from "lucide-react";
import { useState } from "react";
import { api } from "../../api/client";
import type { Channel } from "../../api/types";
import { reportError } from "../../store/workspace";

export function FocusModeToggle({ channel }: { channel: Channel }) {
  const [saving, setSaving] = useState(false);
  const toggle = async () => {
    setSaving(true);
    try {
      await api.setFocusMode(channel.channel_id, !channel.focus_mode);
    } catch (error) {
      reportError(error);
    } finally {
      setSaving(false);
    }
  };
  return (
    <button className={`fv-btn fv-btn--sm${channel.focus_mode ? " fv-btn--primary" : ""}`}
      aria-label="Focus mode" aria-pressed={channel.focus_mode} disabled={saving}
      title={`${channel.focus_mode ? "Show completed replies only" : "Stream all agent activity"} · applies from the next turn`}
      onClick={() => void toggle()}>
      <Focus /><span>Focus {channel.focus_mode ? "on" : "off"}</span>
    </button>
  );
}
