import * as Dialog from "@radix-ui/react-dialog";
import { useQuery } from "@tanstack/react-query";
import { Command } from "cmdk";
import { ArchiveRestore, Bot, Hash, MessageSquare, Moon, Search, Sun } from "lucide-react";
import { useEffect, useState } from "react";
import { api } from "../../api/client";
import { AgentAvatar } from "../../components/Avatar";
import { activeAgents, hueStyle } from "../../lib/agents";
import { useUi } from "../../store/ui";
import { reportError, useWorkspace } from "../../store/workspace";

function useDebounced<T>(value: T, ms: number): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const timer = window.setTimeout(() => setDebounced(value), ms);
    return () => window.clearTimeout(timer);
  }, [value, ms]);
  return debounced;
}

export function CommandPalette() {
  const open = useUi((s) => s.paletteOpen);
  const setOpen = useUi((s) => s.setPaletteOpen);
  const openChannel = useUi((s) => s.openChannel);
  const navigate = useUi((s) => s.navigate);
  const view = useUi((s) => s.view);
  const theme = useUi((s) => s.theme);
  const toggleTheme = useUi((s) => s.toggleTheme);
  const setNewChannelOpen = useUi((s) => s.setNewChannelOpen);
  const agentsById = useWorkspace((s) => s.agents);
  const channels = useWorkspace((s) => s.channels);
  const [query, setQuery] = useState("");
  const term = useDebounced(query.trim(), 180);

  useEffect(() => {
    if (!open) setQuery("");
  }, [open]);

  const results = useQuery({
    queryKey: ["search", term],
    queryFn: () => api.search(term),
    enabled: open && term.length > 0,
    placeholderData: (previous) => previous,
  });

  const go = (action: () => void) => {
    setOpen(false);
    action();
  };

  const agents = activeAgents(agentsById);
  const lower = query.trim().toLowerCase();
  const matches = (text: string) => !lower || text.toLowerCase().includes(lower);
  const conversations = [
    ...agents.filter((a) => a.dm_channel_id && channels[a.dm_channel_id] && matches(a.handle))
      .map((a) => ({ id: a.dm_channel_id!, label: a.handle, agent: a })),
    ...Object.values(channels).filter((c) => c.kind === "channel" && !c.archived_at && matches(c.name))
      .map((c) => ({ id: c.channel_id, label: c.name, agent: undefined })),
  ];
  const actions = [
    { id: "new-agent", label: "New agent", icon: <Bot />, run: () => navigate({ kind: "agent-new", returnTo: view }) },
    { id: "new-channel", label: "New channel", icon: <Hash />, run: () => setNewChannelOpen(true) },
    { id: "theme", label: theme === "dark" ? "Switch to light theme" : "Switch to dark theme", icon: theme === "dark" ? <Sun /> : <Moon />, run: toggleTheme },
  ].filter((a) => matches(a.label));
  const archived = Object.values(channels).filter((c) => c.kind === "channel" && c.archived_at && lower && matches(c.name));
  const restore = async (channelId: string) => {
    try {
      await api.unarchiveChannel(channelId);
      await useWorkspace.getState().refreshSummaries();
      openChannel(channelId);
    } catch (error) {
      reportError(error);
    }
  };
  const messages = term ? results.data?.messages ?? [] : [];
  const nameFor = (authorId: string) => (authorId === "local" ? "you" : agentsById[authorId]?.handle ?? "agent");

  return (
    <Dialog.Root open={open} onOpenChange={setOpen}>
      <Dialog.Portal>
        <Dialog.Overlay className="fv-dialog-overlay" />
        <Dialog.Content className="palette fv-glass" aria-label="Search or jump to">
          <Dialog.Title className="fv-sr-only">Search or jump to</Dialog.Title>
          <Command shouldFilter={false} loop>
            <div className="palette-input">
              <Search />
              <Command.Input value={query} onValueChange={setQuery} placeholder="Search messages, agents and channels…" autoFocus />
            </div>
            <Command.List className="palette-list">
              <Command.Empty className="palette-empty">
                {results.isFetching ? "Searching…" : "Nothing matches."}
              </Command.Empty>
              {conversations.length ? (
                <Command.Group heading="Conversations" className="palette-group">
                  {conversations.map((item) => (
                    <Command.Item key={item.id} value={`conv-${item.id}`} className="fv-menu-item" onSelect={() => go(() => openChannel(item.id))}>
                      {item.agent ? <AgentAvatar agent={item.agent} /> : <Hash />}
                      <span className={item.agent ? "fv-name" : ""} style={item.agent ? hueStyle(item.agent) : undefined}>{item.label}</span>
                    </Command.Item>
                  ))}
                </Command.Group>
              ) : null}
              {messages.length ? (
                <Command.Group heading="Messages" className="palette-group">
                  {messages.map((hit) => (
                    <Command.Item key={`${hit.channel_id}:${hit.seq}:${hit.kind}`} value={`msg-${hit.channel_id}-${hit.seq}-${hit.kind}`}
                      className="fv-menu-item palette-hit" onSelect={() => go(() => openChannel(hit.channel_id, hit.seq))}>
                      <MessageSquare />
                      <span className="palette-hit-text">
                        <span className="fv-meta">{nameFor(hit.author_id)} in {channels[hit.channel_id]?.kind === "dm" ? channels[hit.channel_id]?.name : `#${channels[hit.channel_id]?.name ?? "channel"}`}</span>
                        <span className="palette-hit-body">{hit.text}</span>
                      </span>
                    </Command.Item>
                  ))}
                </Command.Group>
              ) : null}
              {archived.length ? (
                <Command.Group heading="Archived" className="palette-group">
                  {archived.map((channel) => (
                    <Command.Item key={channel.channel_id} value={`arch-${channel.channel_id}`} className="fv-menu-item"
                      onSelect={() => go(() => void restore(channel.channel_id))}>
                      <ArchiveRestore />
                      Restore #{channel.name}
                    </Command.Item>
                  ))}
                </Command.Group>
              ) : null}
              {actions.length ? (
                <Command.Group heading="Actions" className="palette-group">
                  {actions.map((action) => (
                    <Command.Item key={action.id} value={action.id} className="fv-menu-item" onSelect={() => go(action.run)}>
                      {action.icon}
                      {action.label}
                    </Command.Item>
                  ))}
                </Command.Group>
              ) : null}
            </Command.List>
          </Command>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
