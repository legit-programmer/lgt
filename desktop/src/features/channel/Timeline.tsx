import { useEffect, useLayoutEffect, useMemo, useRef, type ReactNode } from "react";
import { api } from "../../api/client";
import { buildTimeline, sortedEvents, type Block } from "../../lib/timeline";
import { useWorkspace } from "../../store/workspace";
import {
  Divider, HumanMessage, Notice, RoutingNotice, RunEnd, RunSegment, type BlockContext,
} from "./blocks";

interface TimelineProps {
  channelId: string;
  ctx: BlockContext;
  anchorSeq?: number;
  empty: ReactNode;
}

const NEAR_BOTTOM = 80;
const EMPTY_QUEUE: never[] = [];

export function Timeline({ channelId, ctx, anchorSeq, empty }: TimelineProps) {
  const timeline = useWorkspace((s) => s.timelines[channelId]);
  const runs = useWorkspace((s) => s.runs);
  const queue = useWorkspace((s) => s.queues[channelId] ?? EMPTY_QUEUE);
  const loadOlder = useWorkspace((s) => s.loadOlder);
  const scroller = useRef<HTMLDivElement>(null);
  const content = useRef<HTMLDivElement>(null);
  const pinned = useRef(true);
  const lastRead = useRef(0);

  const events = useMemo(() => (timeline ? sortedEvents(timeline.events) : []), [timeline]);
  const blocks = useMemo(() => buildTimeline(events, runs, queue), [events, runs, queue]);
  const latestSeq = events.length ? events[events.length - 1].seq : 0;

  // Keep the view pinned to the newest block while content grows (streaming).
  useLayoutEffect(() => {
    const element = scroller.current;
    const inner = content.current;
    if (!element || !inner) return;
    const observer = new ResizeObserver(() => {
      if (pinned.current && anchorSeq === undefined) element.scrollTop = element.scrollHeight;
    });
    observer.observe(inner);
    return () => observer.disconnect();
  }, [anchorSeq]);

  // Jump to a search anchor once it is loaded.
  useEffect(() => {
    if (anchorSeq === undefined) return;
    const target = content.current?.querySelector(`[data-seq="${anchorSeq}"]`);
    if (target) {
      target.scrollIntoView({ block: "center" });
      target.classList.add("is-anchor");
      window.setTimeout(() => target.classList.remove("is-anchor"), 2000);
    }
  }, [anchorSeq, blocks.length]);

  // Advance the server read cursor while the newest message is in view.
  useEffect(() => {
    if (!latestSeq || latestSeq <= lastRead.current || !pinned.current || document.hidden) return;
    const timer = window.setTimeout(() => {
      lastRead.current = latestSeq;
      void api.markRead(channelId, latestSeq).catch(() => undefined);
    }, 400);
    return () => window.clearTimeout(timer);
  }, [channelId, latestSeq]);

  const onScroll = () => {
    const element = scroller.current;
    if (!element) return;
    pinned.current = element.scrollHeight - element.scrollTop - element.clientHeight < NEAR_BOTTOM;
    if (element.scrollTop < 200 && timeline?.hasOlder && !timeline.loading) void loadOlder(channelId);
  };

  if (timeline && !timeline.loading && events.length === 0) {
    return <div className="timeline timeline--empty">{empty}</div>;
  }

  return (
    <div className="timeline" ref={scroller} onScroll={onScroll} role="log" aria-live="polite" aria-busy={timeline?.loading}>
      <div className="timeline-inner" ref={content}>
        {timeline?.hasOlder && timeline.oldestSeq !== null && timeline.oldestSeq > 1 ? (
          <div className="timeline-older fv-meta">{timeline.loading ? "Loading earlier messages…" : "Scroll up for earlier messages"}</div>
        ) : null}
        {blocks.map((block) => <BlockView key={block.key} block={block} ctx={ctx} />)}
      </div>
    </div>
  );
}

function BlockView({ block, ctx }: { block: Block; ctx: BlockContext }) {
  switch (block.type) {
    case "human":
      return block.deleted ? null : <HumanMessage block={block} ctx={ctx} />;
    case "run":
      return <RunSegment block={block} ctx={ctx} />;
    case "routing":
      return <RoutingNotice event={block.event} ctx={ctx} />;
    case "run_end":
      return <RunEnd event={block.event} ctx={ctx} />;
    case "divider":
      return <Divider event={block.event} variant={block.variant} />;
    case "notice":
      return <Notice event={block.event} ctx={ctx} />;
  }
}
