import { cleanup, render } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { Markdown } from "./Markdown";

const agents = {
  agentone: { handle: "builder" },
  agenttwo: { handle: "reviewer" },
};
const handles = new Set(["builder", "reviewer"]);

afterEach(cleanup);

describe("Markdown agent mentions", () => {
  it("renders inline handoffs and delegations as known agent handles", () => {
    const { container } = render(
      <Markdown text="Okay <@agentone:handoff> hey, please check. <@reviewer:delegation> review this." handles={handles} agents={agents} />,
    );

    expect(container.textContent).toBe("Okay @builder hey, please check. @reviewer review this.");
    expect(container.querySelectorAll(".fv-mention")).toHaveLength(2);
  });

  it("keeps transfer examples in code and unknown transfer targets literal", () => {
    const { container } = render(
      <Markdown
        text={"`<@agentone:handoff>` and:\n\n```text\n<@agenttwo:delegation>\n```\n\n<@missing:handoff>"}
        handles={handles}
        agents={agents}
      />,
    );

    expect(container.querySelector("code")?.textContent).toBe("<@agentone:handoff>");
    expect(container.querySelector("pre code")?.textContent?.trimEnd()).toBe("<@agenttwo:delegation>");
    expect(container.textContent).toContain("<@missing:handoff>");
    expect(container.querySelectorAll(".fv-mention")).toHaveLength(0);
  });

  it("continues to style ordinary known handle mentions", () => {
    const { container } = render(<Markdown text="Ask @builder and @unknown." handles={handles} agents={agents} />);

    expect(container.textContent).toBe("Ask @builder and @unknown.");
    expect(container.querySelectorAll(".fv-mention")).toHaveLength(1);
  });

  it("renders the streaming caret inline with the final paragraph", () => {
    const { container } = render(<Markdown text="Streaming <@agentone:handoff>" handles={handles} agents={agents} caret />);

    expect(container.querySelector("p > .fv-caret")).toBeTruthy();
  });
});
