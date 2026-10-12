/** Accept only text selected entirely inside one message's text body. */
export function replySelection(body: HTMLElement | null, selection: Selection | null): string | null {
  if (!body || !selection || selection.isCollapsed || selection.rangeCount !== 1) return null;
  const range = selection.getRangeAt(0);
  if (!body.contains(range.commonAncestorContainer)) return null;
  return selection.toString().trim() || null;
}
