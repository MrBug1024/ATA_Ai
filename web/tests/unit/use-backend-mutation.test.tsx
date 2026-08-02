// @vitest-environment jsdom
import { describe, it, expect, vi } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { act } from "react";
import { useBackendMutation } from "@/lib/hooks/use-backend-mutation";

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}

describe("useBackendMutation", () => {
  it("initial state is idle", () => {
    const { result } = renderHook(() => useBackendMutation(async (x: number) => x * 2));
    expect(result.current.data).toBeNull();
    expect(result.current.isMutating).toBe(false);
    expect(result.current.error).toBeNull();
  });

  it("trigger resolves, stores data and clears isMutating", async () => {
    const fn = vi.fn(async (x: number) => x * 2);
    const { result } = renderHook(() => useBackendMutation(fn));

    let returned: number | undefined;
    await act(async () => {
      returned = await result.current.trigger(21);
    });

    expect(returned).toBe(42);
    expect(fn).toHaveBeenCalledWith(21);
    await waitFor(() => expect(result.current.data).toBe(42));
    expect(result.current.isMutating).toBe(false);
    expect(result.current.error).toBeNull();
  });

  it("trigger rejects, stores error message and rethrows", async () => {
    const fn = vi.fn(async () => {
      throw new Error("后端炸了");
    });
    const { result } = renderHook(() => useBackendMutation(fn));

    await act(async () => {
      await expect(result.current.trigger(undefined)).rejects.toThrow("后端炸了");
    });

    await waitFor(() => expect(result.current.error).toBe("后端炸了"));
    expect(result.current.data).toBeNull();
    expect(result.current.isMutating).toBe(false);
  });

  it("reset clears data and error", async () => {
    const fn = vi.fn(async (x: number) => x);
    const { result } = renderHook(() => useBackendMutation(fn));

    await act(async () => {
      await result.current.trigger(7);
    });
    await waitFor(() => expect(result.current.data).toBe(7));

    act(() => {
      result.current.reset();
    });
    expect(result.current.data).toBeNull();
    expect(result.current.error).toBeNull();
  });

  it("keeps the newest response when an older request finishes last", async () => {
    const first = deferred<string>();
    const second = deferred<string>();
    const fn = vi.fn((request: "first" | "second") =>
      request === "first" ? first.promise : second.promise,
    );
    const { result } = renderHook(() => useBackendMutation(fn));

    let firstResult!: Promise<string>;
    let secondResult!: Promise<string>;
    act(() => {
      firstResult = result.current.trigger("first");
      secondResult = result.current.trigger("second");
    });

    await act(async () => {
      second.resolve("newest");
      await secondResult;
    });
    expect(result.current.data).toBe("newest");
    expect(result.current.isMutating).toBe(false);

    await act(async () => {
      first.resolve("stale");
      await firstResult;
    });
    expect(result.current.data).toBe("newest");
    expect(result.current.isMutating).toBe(false);
    expect(result.current.error).toBeNull();
  });

  it("ignores an older error while the newest request is still pending", async () => {
    const first = deferred<string>();
    const second = deferred<string>();
    const fn = vi.fn((request: "first" | "second") =>
      request === "first" ? first.promise : second.promise,
    );
    const { result } = renderHook(() => useBackendMutation(fn));

    let firstResult!: Promise<string>;
    let secondResult!: Promise<string>;
    act(() => {
      firstResult = result.current.trigger("first");
      secondResult = result.current.trigger("second");
    });

    const firstRejection = expect(firstResult).rejects.toThrow("stale failure");
    await act(async () => {
      first.reject(new Error("stale failure"));
      await firstRejection;
    });
    expect(result.current.error).toBeNull();
    expect(result.current.isMutating).toBe(true);

    await act(async () => {
      second.resolve("newest");
      await secondResult;
    });
    expect(result.current.data).toBe("newest");
    expect(result.current.error).toBeNull();
    expect(result.current.isMutating).toBe(false);
  });

  it("reset invalidates an in-flight request", async () => {
    const pending = deferred<number>();
    const { result } = renderHook(() => useBackendMutation(() => pending.promise));

    let requestResult!: Promise<number>;
    act(() => {
      requestResult = result.current.trigger(undefined);
    });
    expect(result.current.isMutating).toBe(true);

    act(() => {
      result.current.reset();
    });
    expect(result.current.data).toBeNull();
    expect(result.current.error).toBeNull();
    expect(result.current.isMutating).toBe(false);

    await act(async () => {
      pending.resolve(99);
      await requestResult;
    });
    expect(result.current.data).toBeNull();
    expect(result.current.error).toBeNull();
    expect(result.current.isMutating).toBe(false);
  });
});
