// @vitest-environment jsdom
import { describe, it, expect, vi } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { SWRConfig } from "swr";
import { useCaseUploadBatches } from "@/lib/hooks/use-case-upload-batches";

function Wrapper({ children }: { children: React.ReactNode }) {
  return (
    <SWRConfig value={{ provider: () => new Map(), dedupingInterval: 0 }}>
      {children}
    </SWRConfig>
  );
}

describe("useCaseUploadBatches", () => {
  it("returns case upload batches", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({
          case_id: 1,
          upload_batches: [
            { upload_batch_id: "b1", batch_name: "批次1", doc_category: "loan_contract", status: "completed", file_count: 2 },
          ],
        }),
      })
    );

    const { result } = renderHook(() => useCaseUploadBatches(1), { wrapper: Wrapper });
    await waitFor(() => expect(result.current.batches).toHaveLength(1));
    expect(result.current.batches[0].upload_batch_id).toBe("b1");
    expect(result.current.isLoading).toBe(false);
  });

  it("does not fetch when caseId is null", () => {
    const mockFetch = vi.fn();
    vi.stubGlobal("fetch", mockFetch);

    const { result } = renderHook(() => useCaseUploadBatches(null), { wrapper: Wrapper });
    expect(result.current.batches).toHaveLength(0);
    expect(result.current.isLoading).toBe(false);
    expect(mockFetch).not.toHaveBeenCalled();
  });
});
