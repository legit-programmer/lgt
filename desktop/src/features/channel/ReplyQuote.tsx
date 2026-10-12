import type { ReplyQuote, ReplyRequest } from "../../api/types";

export interface ReplyDraft extends ReplyRequest {
  quote: ReplyQuote;
}

export function ReplyQuoteView({ quote, displayName }: { quote: ReplyQuote; displayName: string }) {
  return (
    <blockquote className="fv-reply-quote">
      <span className="fv-meta">Replying to {quote.author_kind === "human" ? displayName : quote.author_handle} · #{quote.seq}{quote.selected ? " · selected text" : ""}</span>
      <div className="fv-reply-text">{quote.text || "(No message text)"}</div>
    </blockquote>
  );
}
