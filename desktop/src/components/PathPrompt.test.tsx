import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { PathPromptHost, requestPath } from "./PathPrompt";

afterEach(cleanup);

describe("workspace path prompt", () => {
  it("resolves the typed path, or null when cancelled", async () => {
    render(<PathPromptHost />);
    let pending!: Promise<string | null>;
    act(() => { pending = requestPath("Working directory for #web", "/srv/old"); });
    const input = screen.getByLabelText("Directory") as HTMLInputElement;
    expect(input.value).toBe("/srv/old");
    fireEvent.change(input, { target: { value: "  /srv/web  " } });
    fireEvent.click(screen.getByRole("button", { name: "Use directory" }));
    await expect(pending).resolves.toBe("/srv/web");

    act(() => { pending = requestPath("Default working directory"); });
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    await expect(pending).resolves.toBeNull();
    expect(screen.queryByLabelText("Directory")).toBeNull();
  });
});
