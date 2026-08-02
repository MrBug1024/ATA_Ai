// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { SWRConfig } from "swr";
import { useUploadBatch } from "@/lib/hooks/use-upload-batch";

function Wrapper({ children }: { children: React.ReactNode }) {
  return (
    <SWRConfig value={{ provider: () => new Map(), dedupingInterval: 0 }}>
      {children}
    </SWRConfig>
  );
}

beforeEach(() => {
  vi.stubGlobal("fetch", vi.fn());
});

describe("useUploadBatch", () => {
  it("returns batch detail", async () => {
    const mockFetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        upload_batch_id: "b1",
        status: "completed",
        file_count: 2,
        files: [{ file_id: 1, file_name: "a.pdf" }],
      }),
    });
    vi.stubGlobal("fetch", mockFetch);

    const { result } = renderHook(() => useUploadBatch("b1"), { wrapper: Wrapper });
    await waitFor(() => expect(result.current.batch).not.toBeNull());
    expect(result.current.batch?.upload_batch_id).toBe("b1");
    expect(result.current.batch?.file_count).toBe(2);
    expect(result.current.isLoading).toBe(false);
  });

  it("does not fetch when batchId is null", async () => {
    const mockFetch = vi.fn();
    vi.stubGlobal("fetch", mockFetch);

    const { result } = renderHook(() => useUploadBatch(null), { wrapper: Wrapper });
    expect(result.current.batch).toBeNull();
    expect(result.current.isLoading).toBe(false);
    expect(mockFetch).not.toHaveBeenCalled();
  });
});
