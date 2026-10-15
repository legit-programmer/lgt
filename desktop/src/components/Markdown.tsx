import { memo } from "react";
import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";

interface MdNode {
  type: string;
  value?: string;
  children?: MdNode[];
  data?: { hName?: string; hProperties?: Record<string, unknown> };
}

const INLINE_TRANSFER_OR_MENTION = /<@([\w.:-]+):(handoff|delegation)>|(?<![\w@])@([\w.:-]+)/g;

/** Wraps known @handles and transfer targets in mention spans; code and links are left alone. */
function remarkMentions(handles: ReadonlySet<string>, agents: Readonly<Record<string, { handle: string }>>, caret: boolean) {
  return () => (tree: MdNode) => {
    const walk = (node: MdNode) => {
      if (!node.children || node.type === "link" || node.type === "inlineCode" || node.type === "code") return;
      const next: MdNode[] = [];
      for (const child of node.children) {
        if (child.type !== "text" || !child.value?.includes("@")) {
          walk(child);
          next.push(child);
          continue;
        }
        let last = 0;
        const value = child.value;
        for (const match of value.matchAll(INLINE_TRANSFER_OR_MENTION)) {
          const transferId = match[1];
          const handle = transferId
            ? agents[transferId]?.handle ?? (handles.has(transferId) ? transferId : undefined)
            : match[3];
          if (!handle || (!transferId && !handles.has(handle))) continue;
          const start = match.index ?? 0;
          if (start > last) next.push({ type: "text", value: value.slice(last, start) });
          next.push({
            type: "mention",
            data: { hName: "span", hProperties: { className: ["fv-mention"] } },
            children: [{ type: "text", value: `@${handle}` }],
          });
          last = start + match[0].length;
        }
        if (last < value.length) next.push({ type: "text", value: value.slice(last) });
      }
      node.children = next;
    };
    walk(tree);

    if (caret) {
      const caretNode: MdNode = {
        type: "caret",
        data: { hName: "span", hProperties: { className: ["fv-caret"] } },
      };
      const appendToLastInlineBlock = (node: MdNode): boolean => {
        const lastChild = node.children?.at(-1);
        if (!lastChild) return false;
        if (lastChild.type === "paragraph" || lastChild.type === "heading") {
          lastChild.children ??= [];
          lastChild.children.push(caretNode);
          return true;
        }
        return appendToLastInlineBlock(lastChild);
      };
      if (!appendToLastInlineBlock(tree)) tree.children?.push(caretNode);
    }
  };
}

const components: Components = {
  a: ({ href, children }) => (
    <a href={href} target="_blank" rel="noreferrer noopener">{children}</a>
  ),
};

interface MarkdownProps {
  text: string;
  handles: ReadonlySet<string>;
  agents: Readonly<Record<string, { handle: string }>>;
  caret?: boolean;
}

function MarkdownImpl({ text, handles, agents, caret }: MarkdownProps) {
  return (
    <>
      <ReactMarkdown remarkPlugins={[remarkGfm, remarkMentions(handles, agents, caret ?? false)]} components={components}>
        {text}
      </ReactMarkdown>
    </>
  );
}

export const Markdown = memo(MarkdownImpl);
