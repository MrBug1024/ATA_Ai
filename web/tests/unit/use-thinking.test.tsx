// @vitest-environment jsdom
import { describe, it, expect } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { useThinking } from "@/lib/assistant-ui/use-thinking";

describe("useThinking", () => {
  it("初始 map 为空", () => {
    const { result } = renderHook(() => useThinking());
    expect(result.current.thinkingMap.size).toBe(0);
  });

  it("initThinking 创建新条目", () => {
    const { result } = renderHook(() => useThinking());
    act(() => result.current.initThinking("stream-1"));
    const state = result.current.thinkingMap.get("stream-1");
    expect(state).toBeDefined();
    expect(state?.steps).toEqual([]);
    expect(state?.isComplete).toBe(false);
    expect(typeof state?.startedAt).toBe("number");
  });

  it("updateThinking 在无 streamId 时忽略", () => {
    const { result } = renderHook(() => useThinking());
    act(() =>
      result.current.updateThinking({ type: "node", title: "n1", nodeType: "llm" })
    );
    expect(result.current.thinkingMap.size).toBe(0);
  });

  it("每个 node 事件追加一个 step", () => {
    const { result } = renderHook(() => useThinking());
    act(() => result.current.initThinking("s1"));
    act(() =>
      result.current.updateThinking({ type: "node", title: "n1", nodeType: "llm" })
    );
    act(() =>
      result.current.updateThinking({
        type: "node",
        title: "n2",
        nodeType: "tool",
        payload: { foo: 1 },
      })
    );
    const state = result.current.thinkingMap.get("s1");
    expect(state?.steps).toEqual([
      { title: "n1", nodeType: "llm", payload: undefined },
      { title: "n2", nodeType: "tool", payload: { foo: 1 } },
    ]);
  });

  it("completeThinking 设置 isComplete + completedAt 并清空 streamIdRef", () => {
    const { result } = renderHook(() => useThinking());
    act(() => result.current.initThinking("s1"));
    act(() => result.current.completeThinking());
    const state = result.current.thinkingMap.get("s1");
    expect(state?.isComplete).toBe(true);
    expect(typeof state?.completedAt).toBe("number");
    expect(result.current.streamIdRef.current).toBe("");
  });

  it("completeThinking 无 streamId 时 no-op", () => {
    const { result } = renderHook(() => useThinking());
    act(() => result.current.completeThinking());
    expect(result.current.thinkingMap.size).toBe(0);
  });

  it("updateThinking 在 state 不存在时 no-op", () => {
    const { result } = renderHook(() => useThinking());
    act(() => {
      result.current.streamIdRef.current = "nonexistent";
      result.current.updateThinking({ type: "node", title: "x", nodeType: "y" });
    });
    expect(result.current.thinkingMap.size).toBe(0);
  });
});
