import { describe, it, expect } from "vitest";
import { cn } from "@/lib/utils";

describe("cn", () => {
  it("合并多个类名", () => {
    expect(cn("a", "b")).toBe("a b");
  });

  it("过滤假值并支持条件类名", () => {
    expect(cn("a", false, null, undefined, "b")).toBe("a b");
    expect(cn("a", { b: true, c: false })).toBe("a b");
  });

  it("tailwind 冲突时后者覆盖前者", () => {
    expect(cn("px-2", "px-4")).toBe("px-4");
  });
});
