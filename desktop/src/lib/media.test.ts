import { describe, expect, it } from "vitest";
import { freeFilename, safeFilename } from "./media";

describe("saving attachments on a phone", () => {
  it("keeps a server-supplied name inside one path segment", () => {
    expect(safeFilename("report.pdf")).toBe("report.pdf");
    expect(safeFilename("../../etc/passwd")).toBe(".._.._etc_passwd");
    expect(safeFilename("a\\\\b:c\nd")).toBe("a__b_c_d");
    expect(safeFilename("..")).toBe("attachment");
    expect(safeFilename("  ")).toBe("attachment");
  });

  it("numbers copies instead of overwriting an earlier download", async () => {
    const existing = new Set(["report.pdf", "report (1).pdf", "notes"]);
    const taken = async (name: string) => existing.has(name);
    expect(await freeFilename("report.pdf", taken)).toBe("report (2).pdf");
    expect(await freeFilename("notes", taken)).toBe("notes (1)");
    expect(await freeFilename(".env", taken)).toBe(".env");
    expect(await freeFilename("fresh.png", taken)).toBe("fresh.png");
  });
});
