import { useQuery } from "@tanstack/react-query";
import { ArrowRight, ArrowUp, AtSign, Ban, Check, FileText, Loader2, Paperclip, Slash, X } from "lucide-react";
import { useEffect, useMemo, useRef, useState, type ClipboardEvent, type DragEvent, type KeyboardEvent } from "react";
import { api } from "../../api/client";
import type { Agent, Attachment, Command, SkillEntry } from "../../api/types";
import { AgentAvatar } from "../../components/Avatar";
import { bytes } from "../../lib/format";
import { reportError } from "../../store/workspace";
import { ReplyQuoteView, type ReplyDraft } from "./ReplyQuote";
import { SkillDialog } from "./SkillDialog";
import { harnessLabel } from "../../lib/agents";
import { ProviderLogo } from "../../components/ProviderLogo";

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
  reply: ReplyDraft | null;
  replyLoading: boolean;
  displayName: string;
  onClearReply: () => void;
  skillRevision?: string;
}

interface Suggestion {
  key: string;
  label: string;
  detail: string;
  insert: string;
  agent?: Agent;
  skill?: SkillEntry;
}

// Drafts survive switching conversations within this window.
const drafts = new Map<string, { text: string; skill: SkillEntry | null; agentId: string | null }>();
let localIds = 0;

export function Composer({ channelId, placeholder, members, allowMentions, disabled, reply, replyLoading, displayName, onClearReply, skillRevision }: ComposerProps) {
  const [text, setText] = useState(() => drafts.get(channelId)?.text ?? "");
  const [files, setFiles] = useState<Pending[]>([]);
  const [sending, setSending] = useState(false);
  const [caret, setCaret] = useState(0);
  const [highlight, setHighlight] = useState(0);
  const [dragging, setDragging] = useState(false);
  const [dismissed, setDismissed] = useState(false);
  const [selectedSkill, setSelectedSkill] = useState<SkillEntry | null>(() => drafts.get(channelId)?.skill ?? null);
  const [selectedAgent, setSelectedAgent] = useState<string | null>(() => drafts.get(channelId)?.agentId ?? null);
  const [choosingAgent, setChoosingAgent] = useState(false);
  const area = useRef<HTMLTextAreaElement>(null);
  const suggestionList = useRef<HTMLDivElement>(null);
  const picker = useRef<HTMLInputElement>(null);
  const commands = useQuery({ queryKey: ["commands"], queryFn: api.commands, staleTime: Infinity });
  const skills = useQuery({ queryKey: ["channel-skills", channelId, skillRevision],
    queryFn: () => api.channelSkills(channelId), enabled: text.startsWith("/") || selectedSkill !== null,
    staleTime: 0, retry: false });
  const currentSkill = skills.data?.skills.find((skill) => skill.skill_id === selectedSkill?.skill_id) ?? selectedSkill;
  useEffect(() => { if (reply) area.current?.focus(); }, [reply]);

  useEffect(() => {
    drafts.set(channelId, { text, skill: selectedSkill, agentId: selectedAgent });
  }, [channelId, text, selectedSkill, selectedAgent]);

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
      const installed = (skills.data?.skills ?? []).filter((skill) => command[1] === "list" ||
        skill.name.toLowerCase().startsWith(command[1].toLowerCase()) || `${skill.harness}:${skill.name}`.startsWith(command[1]));
      return [...(command[1] === "list" ? [] : commands.data ?? [])
        .filter((c: Command) => c.name.slice(1).startsWith(command[1]))
        .map((c) => ({ key: c.name, label: c.usage, detail: c.description, insert: `${c.name} ` })),
        ...installed.map((skill) => ({ key: skill.skill_id, label: `/${skill.name}`, skill,
          detail: `${harnessLabel(skill.harness)} · ${skill.plugin_id ?? skill.scope} · ${skill.status === "ready"
            ? `run with ${skill.agents.find((agent) => agent.agent_id === skill.default_agent_id)?.handle}`
            : skill.status === "choose_agent" ? "choose an agent" : skill.reason}`,
          insert: `/${skill.name} ` }))];
    }
    const mention = allowMentions ? /(?:^|\s)@([\w.:-]*)$/.exec(before) : null;
    if (mention) {
      const query = mention[1].toLowerCase();
      return members
        .filter((agent) => agent.handle.toLowerCase().startsWith(query))
        .map((agent) => ({ key: agent.agent_id, label: `@${agent.handle}`, detail: agent.description, insert: `@${agent.handle} `, agent }));
    }
    return [];
  }, [text, caret, commands.data, skills.data, members, allowMentions, dismissed]);

  useEffect(() => setHighlight(0), [suggestions.length]);
  useEffect(() => {
    suggestionList.current?.querySelector<HTMLElement>('[data-selected="true"]')?.scrollIntoView?.({ block: "nearest" });
  }, [highlight, suggestions.length]);

  const applySuggestion = (suggestion: Suggestion) => {
    setSelectedSkill(suggestion.skill ?? null);
    setSelectedAgent(null);
    setChoosingAgent(!!suggestion.skill && suggestion.skill.status !== "ready");
    setDismissed(true);
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
  const executor = selectedAgent ?? currentSkill?.default_agent_id;
  const skillBlocked = currentSkill && (skills.isLoading || skills.isError ||
    !skills.data?.skills.some((skill) => skill.skill_id === currentSkill.skill_id) ||
    !executor || !currentSkill.eligible_agent_ids.includes(executor));
  const canSend = !disabled && !sending && !uploading && !replyLoading && !skillBlocked && (text.trim().length > 0 || ready.length > 0);

  const send = async () => {
    if (!canSend) return;
    setSending(true);
    try {
      let skill = currentSkill;
      const match = /^\/(\S+)(?:\s([\s\S]*))?$/.exec(text);
      if (!skill && match && !["new", "cwd", "cancel", "list"].includes(match[1])) {
        const fresh = await skills.refetch();
        const matches = fresh.data?.skills.filter((entry) => [entry.name, `${entry.harness}:${entry.name}`].includes(match[1])) ?? [];
        if (matches.length !== 1) throw new Error("Skill is unavailable or ambiguous. Select its installation from /list.");
        skill = matches[0];
        setSelectedSkill(skill);
        setSelectedAgent(null);
        if (!skill.default_agent_id) { setChoosingAgent(true); return; }
      }
      const metadata = { attachments: ready.map((f) => f.attachment!.attachment_id),
        ...(reply ? { reply_to_seq: reply.reply_to_seq, reply_selection: reply.reply_selection } : {}) };
      if (skill) {
        await api.invokeSkill(channelId, { skill_id: skill.skill_id,
          agent_id: selectedAgent ?? skill.default_agent_id ?? undefined, arguments: match?.[2] ?? "", ...metadata });
      } else await api.sendMessage(channelId, { text, ...metadata });
      files.forEach((f) => f.preview && URL.revokeObjectURL(f.preview));
      setFiles([]);
      setText("");
      setSelectedSkill(null);
      setSelectedAgent(null);
      drafts.delete(channelId);
      onClearReply();
    } catch (error) {
      reportError(error);
      if (currentSkill) { await skills.refetch(); setChoosingAgent(true); }
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
    if (event.key === "Escape" && (reply || replyLoading)) onClearReply();
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
      {reply || replyLoading ? (
        <div className="composer-reply" aria-busy={replyLoading}>
          {replyLoading ? <span className="fv-meta">Loading reply quote…</span> : reply ? <ReplyQuoteView quote={reply.quote} displayName={displayName} /> : null}
          <button className="fv-icon-btn fv-icon-btn--sm" aria-label="Remove reply" onClick={onClearReply}><X /></button>
        </div>
      ) : null}
      {suggestions.length ? (
        <div ref={suggestionList} className="composer-suggest fv-glass fv-menu" role="listbox">
          {suggestions.map((suggestion, index) => (
            <button key={suggestion.key} role="option" aria-selected={index === highlight}
              className="fv-menu-item" data-selected={index === highlight}
              title={suggestion.skill?.description ?? suggestion.detail}
              onMouseDown={(event) => { event.preventDefault(); applySuggestion(suggestion); }}>
              {suggestion.agent ? <AgentAvatar agent={suggestion.agent} /> : suggestion.skill ? <ProviderLogo harness={suggestion.skill.harness} /> : <Slash />}
              <span className="fv-mono">{suggestion.label}</span>
              <span className="fv-meta composer-suggest-detail">{suggestion.detail}</span>
              {suggestion.skill ? <span className={`fv-chip ${suggestion.skill.status === "ready" ? "fv-chip--success"
                : suggestion.skill.status === "unavailable" ? "fv-chip--failed" : ""}`}>
                {suggestion.skill.status === "ready" ? <Check /> : suggestion.skill.status === "unavailable" ? <Ban /> : <ArrowRight />}
                {suggestion.skill.status === "ready" ? "Ready" : suggestion.skill.status === "unavailable" ? "Unavailable" : "Choose"}
              </span> : null}
            </button>
          ))}
        </div>
      ) : null}
      {text.startsWith("/") && skills.isFetching ? <span className="fv-meta"><Loader2 size={12} className="spin" /> Discovering skills…</span> : null}
      {text.startsWith("/") && skills.error ? <span className="fv-error-text">{skills.error.message}</span> : null}
      {text.startsWith("/") && skills.data?.errors.length ? <div className="fv-meta" role="status">
        {skills.data.errors.map((error, index) => <div key={index}>{harnessLabel(error.harness)}: {error.message}</div>)}
      </div> : null}
      {currentSkill ? <div className="composer-skill fv-meta">
        <ProviderLogo harness={currentSkill.harness} /><span>/{currentSkill.name} · {executor
          ? `run with ${currentSkill.agents.find((agent) => agent.agent_id === executor)?.handle ?? "selected agent"}`
          : "requires a compatible agent"}</span>
        <button className="fv-btn fv-btn--ghost fv-btn--sm" onClick={() => setChoosingAgent(true)}>Choose agent or backend</button>
        <button className="fv-icon-btn fv-icon-btn--sm" aria-label="Clear skill selection" onClick={() => {
          setSelectedSkill(null); setSelectedAgent(null); setText("");
        }}><X /></button>
      </div> : null}
      {currentSkill && skills.data && !skills.data.skills.some((skill) => skill.skill_id === currentSkill.skill_id)
        ? <p className="fv-error-text">This installation is no longer available. Select another skill from /list.</p> : null}
      {choosingAgent && currentSkill ? <SkillDialog skill={currentSkill} channelId={channelId}
        kind={skills.data?.kind ?? (allowMentions ? "channel" : "dm")} onClose={() => setChoosingAgent(false)}
        onRefresh={() => skills.refetch()} onChoose={(agentId) => { setSelectedAgent(agentId); setChoosingAgent(false); }} /> : null}
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
        rows={1}
        value={text}
        placeholder={placeholder}
        disabled={disabled}
        aria-label={placeholder}
        onChange={(event) => {
          const value = event.target.value;
          if (selectedSkill && value.split(/\s/)[0] !== `/${selectedSkill.name}`) { setSelectedSkill(null); setSelectedAgent(null); }
          setText(value); setCaret(event.target.selectionStart); setDismissed(false);
        }}
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
