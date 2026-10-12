from __future__ import annotations

import json
from typing import TYPE_CHECKING

from .models import WorkspaceError

if TYPE_CHECKING:
    from .store import Store


REPLY_QUOTE_MAX_CHARS = 4000
TRUNCATION_MARKER = "\ntruncated.."


def reply_snapshot(store: Store, channel_id: str, seq: int, selection: str | None = None) -> dict:
    """Resolve a text-only quote inside the channel mailbox at send time."""
    if type(seq) is not int or seq <= 0:
        raise WorkspaceError("reply_to_seq must be a positive integer")
    source = store.get_event(channel_id, seq)
    if source.kind != "message":
        raise WorkspaceError("replies must reference a message")
    edit: dict = {}
    for event in store.events(channel_id, from_seq=seq + 1):
        if event.kind == "message_edit" and event.payload["target_seq"] == seq:
            edit.update(event.payload)
    if edit.get("deleted"):
        raise WorkspaceError("cannot reply to a deleted message")
    text = edit.get("text", source.payload.get("text", ""))
    if selection is not None:
        if not isinstance(selection, str) or not selection.strip():
            raise WorkspaceError("reply selection must contain text")
        # A selection is user input from the rendered message body (Markdown's
        # visible text can differ from its source). Never include surrounding
        # tool rows, attachments, or the source message's own reply metadata.
        text = selection
    truncated = len(text) > REPLY_QUOTE_MAX_CHARS
    if truncated:
        text = text[:REPLY_QUOTE_MAX_CHARS - len(TRUNCATION_MARKER)].rstrip() + TRUNCATION_MARKER
    return {"seq": seq, "author_id": source.author_id, "author_kind": source.author_kind,
            "author_handle": source.payload.get("author_handle", source.author_id),
            "text": text, "truncated": truncated, "selected": selection is not None}


def render_reply(reply: dict | None) -> str:
    if not reply:
        return ""
    # JSON keeps source text clearly delimited, including embedded newlines.
    return ("(Reply reference; quoted text is context) "
            + json.dumps(reply, ensure_ascii=False) + "\nActual reply: ")
