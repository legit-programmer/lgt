import { useQuery } from "@tanstack/react-query";
import { ArrowUp, AtSign, FileText, Loader2, Paperclip, Slash, X } from "lucide-react";
import { useEffect, useMemo, useRef, useState, type ClipboardEvent, type DragEvent, type KeyboardEvent } from "react";
import { api } from "../../api/client";
import type { Agent, Attachment, Command } from "../../api/types";
import { AgentAvatar } from "../../components/Avatar";
import { bytes } from "../../lib/format";
import { reportError } from "../../store/workspace";

interface Pending {
  localId: number;
  file: File;
  preview: string | null;
  attachment: Attachment | null;
  error: string | null;
}

interface ComposerProps {
  channelId: string;
  placeholder: string;
  members: Agent[];
  allowMentions: boolean;
  disabled?: boolean;
}

interface Suggestion {
  key: string;
  label: string;
  detail: string;
  insert: string;
  agent?: Agent;
}

// Drafts survive switching conversations within this window.
const drafts = new Map<string, string>();
let localIds = 0;

export function Composer({ channelId, placeholder, members, allowMentions, disabled }: ComposerProps) {
  const [text, setText] = useState(() => drafts.get(channelId) ?? "");
  const [files, setFiles] = useState<Pending[]>([]);
  const [sending, setSending] = useState(false);
  const [caret, setCaret] = useState(0);
  const [highlight, setHighlight] = useState(0);
  const [dragging, setDragging] = useState(false);
  const [dismissed, setDismissed] = useState(false);
  const area = useRef<HTMLTextAreaElement>(null);
  const picker = useRef<HTMLInputElement>(null);
  const commands = useQuery({ queryKey: ["commands"], queryFn: api.commands, staleTime: Infinity });

  useEffect(() => {
    drafts.set(channelId, text);
  }, [channelId, text]);

  // Grow with the text up to a cap.
  useEffect(() => {
    const element = area.current;
    if (!element) return;
    element.style.height = "auto";
    element.style.height = `${Math.min(element.scrollHeight, 240)}px`;
  }, [text]);

  const filesRef = useRef(files);
  filesRef.current = files;
  useEffect(() => () => filesRef.current.forEach((f) => f.preview && URL.revokeObjectURL(f.preview)), []);

  const suggestions = useMemo<Suggestion[]>(() => {
    if (dismissed) return [];
    const before = text.slice(0, caret);
    const command = /^\/(\S*)$/.exec(before);
    if (command) {
      return (commands.data ?? [])
        .filter((c: Command) => c.name.slice(1).startsWith(command[1]))
        .map((c) => ({ key: c.name, label: c.usage, detail: c.description, insert: `${c.name} ` }));
    }
    const mention = allowMentions ? /(?:^|\s)@([\w.:-]*)$/.exec(before) : null;
    if (mention) {
      const query = mention[1].toLowerCase();
      return members
        .filter((agent) => agent.handle.toLowerCase().startsWith(query))
        .map((agent) => ({ key: agent.agent_id, label: `@${agent.handle}`, detail: agent.description, insert: `@${agent.handle} `, agent }));
    }
    return [];
  }, [text, caret, commands.data, members, allowMentions, dismissed]);

  useEffect(() => setHighlight(0), [suggestions.length]);

  const applySuggestion = (suggestion: Suggestion) => {
    const before = text.slice(0, caret);
    const after = text.slice(caret);
    const start = suggestion.insert.startsWith("/") ? 0 : before.lastIndexOf("@");
    const next = before.slice(0, start) + suggestion.insert + after;
    setText(next);
    const position = start + suggestion.insert.length;
    requestAnimationFrame(() => {
      area.current?.focus();
      area.current?.setSelectionRange(position, position);
      setCaret(position);
    });
  };

  const upload = (list: FileList | File[]) => {
    const added: Pending[] = Array.from(list).map((file) => ({
      localId: ++localIds,
      file,
      preview: file.type.startsWith("image/") ? URL.createObjectURL(file) : null,
      attachment: null,
      error: null,
    }));
    setFiles((current) => [...current, ...added]);
    for (const pending of added) {
      api.uploadAttachment(channelId, pending.file)
        .then((attachment) => setFiles((current) => current.map((f) => (f.localId === pending.localId ? { ...f, attachment } : f))))
        .catch((error: Error) => setFiles((current) => current.map((f) => (f.localId === pending.localId ? { ...f, error: error.message } : f))));
    }
  };

  const removeFile = (pending: Pending) => {
    setFiles((current) => current.filter((f) => f.localId !== pending.localId));
    if (pending.preview) URL.revokeObjectURL(pending.preview);
    if (pending.attachment) void api.deleteAttachment(pending.attachment.attachment_id).catch(() => undefined);
  };

  const uploading = files.some((f) => !f.attachment && !f.error);
  const ready = files.filter((f) => f.attachment);
  const canSend = !disabled && !sending && !uploading && (text.trim().length > 0 || ready.length > 0);

  const send = async () => {
    if (!canSend) return;
    setSending(true);
    try {
      await api.sendMessage(channelId, { text, attachments: ready.map((f) => f.attachment!.attachment_id) });
      files.forEach((f) => f.preview && URL.revokeObjectURL(f.preview));
      setFiles([]);
      setText("");
      drafts.delete(channelId);
    } catch (error) {
      reportError(error);
    } finally {
      setSending(false);
      area.current?.focus();
    }
  };

  const onKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (suggestions.length) {
      if (event.key === "ArrowDown" || event.key === "ArrowUp") {
        event.preventDefault();
        const step = event.key === "ArrowDown" ? 1 : -1;
        setHighlight((h) => (h + step + suggestions.length) % suggestions.length);
        return;
      }
      if (event.key === "Enter" || event.key === "Tab") {
        event.preventDefault();
        applySuggestion(suggestions[highlight]);
        return;
      }
      if (event.key === "Escape") {
        setDismissed(true);
        return;
      }
    }
    if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault();
      void send();
    }
  };

  const onPaste = (event: ClipboardEvent<HTMLTextAreaElement>) => {
    const pasted = Array.from(event.clipboardData.files);
    if (pasted.length) {
      event.preventDefault();
      upload(pasted);
    }
  };

  const onDrop = (event: DragEvent) => {
    event.preventDefault();
    setDragging(false);
    if (event.dataTransfer.files.length) upload(event.dataTransfer.files);
  };

  const insert = (value: string) => {
    const element = area.current;
    const position = element?.selectionStart ?? text.length;
    const needsSpace = value === "@" && position > 0 && !/\s$/.test(text.slice(0, position));
    const piece = needsSpace ? ` ${value}` : value;
    const next = value === "/" ? `/${text}` : text.slice(0, position) + piece + text.slice(position);
    setText(next);
    const cursor = value === "/" ? 1 : position + piece.length;
    requestAnimationFrame(() => {
      element?.focus();
      element?.setSelectionRange(cursor, cursor);
      setCaret(cursor);
    });
  };

  return (
    <div className={`composer${dragging ? " is-dragging" : ""}`}
      onDragOver={(event) => { event.preventDefault(); setDragging(true); }}
      onDragLeave={() => setDragging(false)} onDrop={onDrop}>
      {suggestions.length ? (
        <div className="composer-suggest fv-glass fv-menu" role="listbox">
          {suggestions.map((suggestion, index) => (
            <button key={suggestion.key} role="option" aria-selected={index === highlight}
              className="fv-menu-item" data-selected={index === highlight}
              onMouseDown={(event) => { event.preventDefault(); applySuggestion(suggestion); }}>
              {suggestion.agent ? <AgentAvatar agent={suggestion.agent} /> : <Slash />}
              <span className="fv-mono">{suggestion.label}</span>
              <span className="fv-meta composer-suggest-detail">{suggestion.detail}</span>
            </button>
          ))}
        </div>
      ) : null}
      {files.length ? (
        <div className="composer-files">
          {files.map((pending) => (
            <span key={pending.localId} className={`fv-attachment composer-file${pending.error ? " is-error" : ""}`}
              title={pending.error ?? pending.file.name}>
              {pending.preview ? <img src={pending.preview} alt="" className="composer-thumb" /> : <FileText size={16} />}
              <span className="fv-attachment-name">{pending.file.name}</span>
              <span className="fv-meta">
                {pending.error ? "failed" : pending.attachment ? bytes(pending.file.size) : <Loader2 size={12} className="spin" />}
              </span>
              <button className="fv-icon-btn fv-icon-btn--sm" aria-label={`Remove ${pending.file.name}`} onClick={() => removeFile(pending)}>
                <X />
              </button>
            </span>
          ))}
        </div>
      ) : null}
      <textarea
        ref={area}
        className="composer-input"
        rows={2}
        value={text}
        placeholder={placeholder}
        disabled={disabled}
        aria-label={placeholder}
        onChange={(event) => { setText(event.target.value); setCaret(event.target.selectionStart); setDismissed(false); }}
        onSelect={(event) => setCaret(event.currentTarget.selectionStart)}
        onKeyDown={onKeyDown}
        onPaste={onPaste}
      />
      <div className="composer-bar">
        {allowMentions ? (
          <button className="fv-icon-btn" aria-label="Mention an agent" onClick={() => insert("@")}><AtSign /></button>
        ) : null}
        <button className="fv-icon-btn" aria-label="Insert a command" onClick={() => insert("/")}><Slash /></button>
        <button className="fv-icon-btn" aria-label="Attach files" onClick={() => picker.current?.click()}><Paperclip /></button>
        <input ref={picker} type="file" multiple hidden onChange={(event) => { if (event.target.files) upload(event.target.files); event.target.value = ""; }} />
        <span className="composer-hint fv-meta">↵ send · ⇧↵ newline</span>
        <button className="fv-btn fv-btn--primary" onClick={send} disabled={!canSend}>
          <ArrowUp /> Send
        </button>
      </div>
    </div>
  );
}
