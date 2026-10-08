import { describe, expect, it } from "vitest";
import { splitArgs } from "../features/agents/AgentForm";
import { bytes, clock, duration, middleTruncate, shortPath, tokens } from "./format";

describe("format", () => {
  it("formats durations, clocks, tokens and sizes like the design", () => {
    expect(duration(100)).toBe("0.1s");
    expect(duration(48_000)).toBe("48s");
    expect(duration(112_000)).toBe("1m 52s");
    expect(clock(64_000)).toBe("1:04");
    expect(tokens(12_400)).toBe("12k");
    expect(tokens(3_100)).toBe("3.1k");
    expect(bytes(9_626)).toBe("9.4 KB");
  });

  it("shortens home paths and keeps both ends of long ones", () => {
    expect(shortPath(String.raw`C:\Users\sam\code\lgt`)).toBe("~/code/lgt");
    expect(middleTruncate("abcdefghijklmnopqrstuvwxyz", 11)).toBe("abcd…uvwxyz");
  });

  it("splits command lines into argv", () => {
    expect(splitArgs('--max-turns 40 --note "two words"')).toEqual(["--max-turns", "40", "--note", "two words"]);
  });
});
