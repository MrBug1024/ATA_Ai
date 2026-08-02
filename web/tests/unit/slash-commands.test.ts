import { describe, it, expect } from "vitest";
import {
  parseSlash,
  stripSlashLine,
  filterCommands,
  type SlashCommandDef,
} from "@/lib/utils/slash-commands";

describe("parseSlash", () => {
  it("不以 / 开头时返回 null", () => {
    expect(parseSlash("")).toBeNull();
    expect(parseSlash("hello")).toBeNull();
    expect(parseSlash(" /case")).toBeNull();
  });

  it("单独 / 时 command 为空串", () => {
    expect(parseSlash("/")).toEqual({ command: "", arg: "", lineEnd: 1 });
  });

  it("部分命令前缀", () => {
    expect(parseSlash("/c")).toEqual({ command: "c", arg: "", lineEnd: 2 });
    expect(parseSlash("/ca")).toEqual({ command: "ca", arg: "", lineEnd: 3 });
  });

  it("完整命令 + 空参数", () => {
    expect(parseSlash("/case")).toEqual({ command: "case", arg: "", lineEnd: 5 });
  });

  it("命令 + 空格 + 参数", () => {
    expect(parseSlash("/case 张三")).toEqual({
      command: "case",
      arg: "张三",
      lineEnd: 8,
    });
  });

  it("命令行截止于首个换行，arg 不包含后续行", () => {
    const r = parseSlash("/case 张三\n帮我分析");
    expect(r).toEqual({ command: "case", arg: "张三", lineEnd: 8 });
  });

  it("arg 去除首尾空格", () => {
    expect(parseSlash("/case   abc  ")?.arg).toBe("abc");
  });
});

describe("stripSlashLine", () => {
  it("无 / 命令时原样返回", () => {
    expect(stripSlashLine("hello")).toBe("hello");
  });

  it("移除整行命令", () => {
    expect(stripSlashLine("/case")).toBe("");
    expect(stripSlashLine("/case 张三")).toBe("");
  });

  it("保留命令行之后的内容", () => {
    expect(stripSlashLine("/case 张三\n帮我分析")).toBe("帮我分析");
    expect(stripSlashLine("/c\nline1\nline2")).toBe("line1\nline2");
  });
});

const COMMANDS: SlashCommandDef[] = [
  { key: "case", label: "/case", description: "选择要分析的案件" },
  { key: "clear", label: "/clear", description: "清空会话" },
  { key: "help", label: "/help", description: "帮助" },
];

describe("filterCommands", () => {
  it("空前缀返回所有命令", () => {
    expect(filterCommands(COMMANDS, "").map((c) => c.key)).toEqual([
      "case",
      "clear",
      "help",
    ]);
  });

  it("按前缀过滤", () => {
    expect(filterCommands(COMMANDS, "c").map((c) => c.key)).toEqual(["case", "clear"]);
    expect(filterCommands(COMMANDS, "ca").map((c) => c.key)).toEqual(["case"]);
    expect(filterCommands(COMMANDS, "h").map((c) => c.key)).toEqual(["help"]);
  });

  it("无匹配返回空数组", () => {
    expect(filterCommands(COMMANDS, "xyz")).toEqual([]);
  });

  it("大小写不敏感", () => {
    expect(filterCommands(COMMANDS, "CA").map((c) => c.key)).toEqual(["case"]);
  });
});
