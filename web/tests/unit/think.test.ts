import { describe, it, expect } from "vitest";
import { extractThink, stripThink } from "@/lib/utils/think";

describe("extractThink", () => {
  it("无 think 标签时返回原文", () => {
    expect(extractThink("Hello world")).toEqual({
      thinkText: "",
      displayText: "Hello world",
      thinkDone: false,
    });
  });

  it("提取 think 内容与显示内容", () => {
    expect(extractThink("<think>推理过程</think>最终答案")).toEqual({
      thinkText: "推理过程",
      displayText: "最终答案",
      thinkDone: true,
    });
  });

  it("未闭合的 think 标签", () => {
    expect(extractThink("<think>流式中...")).toEqual({
      thinkText: "流式中...",
      displayText: "",
      thinkDone: false,
    });
  });

  it("嵌套 think 标签", () => {
    expect(extractThink("<think>outer<think>inner</think>still</think>display")).toEqual({
      thinkText: "outerinnerstill",
      displayText: "display",
      thinkDone: true,
    });
  });

  it("think 前后都有显示内容", () => {
    expect(extractThink("前缀 <think>思考</think> 后缀")).toEqual({
      thinkText: "思考",
      displayText: "前缀  后缀",
      thinkDone: true,
    });
  });
});

describe("stripThink", () => {
  it("移除 think 内容并 trim", () => {
    expect(stripThink("<think>推理</think>  答案  ")).toBe("答案");
  });

  it("无标签时原样返回（已 trim）", () => {
    expect(stripThink("  hello  ")).toBe("hello");
  });
});
