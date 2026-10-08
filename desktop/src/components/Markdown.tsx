import { memo, type ReactNode } from "react";
import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";

interface MdNode {
  type: string;
  value?: string;
  children?: MdNode[];
  data?: { hName?: string; hProperties?: Record<string, unknown> };
}

const MENTION = /(?<![\w@])@([\w.:-]+)/g;

/** Wraps known @handles in a mention span; code and links are left alone. */
function remarkMentions(handles: ReadonlySet<string>) {
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
        for (const match of value.matchAll(MENTION)) {
          if (!handles.has(match[1])) continue;
          const start = match.index ?? 0;
          if (start > last) next.push({ type: "text", value: value.slice(last, start) });
          next.push({
            type: "mention",
            data: { hName: "span", hProperties: { className: ["fv-mention"] } },
            children: [{ type: "text", value: match[0] }],
          });
          last = start + match[0].length;
        }
        if (last < value.length) next.push({ type: "text", value: value.slice(last) });
      }
      node.children = next;
    };
    walk(tree);
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
  trailing?: ReactNode;
}

function MarkdownImpl({ text, handles, trailing }: MarkdownProps) {
  return (
    <>
      <ReactMarkdown remarkPlugins={[remarkGfm, remarkMentions(handles)]} components={components}>
        {text}
      </ReactMarkdown>
      {trailing}
    </>
  );
}

export const Markdown = memo(MarkdownImpl);
