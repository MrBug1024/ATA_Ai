// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { act } from "react";

// Mock fetch globally
const mockFetch = vi.fn();
vi.stubGlobal("fetch", mockFetch);

// Stub env so langgraphUrl resolves to http://test
vi.stubEnv("NEXT_PUBLIC_LANGGRAPH_API_BASE_URL", "http://test");

beforeEach(() => { mockFetch.mockReset(); });

describe("useEvidenceResolve", () => {
  it("returns null data before trigger", async () => {
    const { useEvidenceResolve } = await import("@/lib/hooks/use-evidence-resolve");
    const { result } = renderHook(() => useEvidenceResolve());
    expect(result.current.data).toBeNull();
    expect(result.current.isMutating).toBe(false);
  });

  it("calls /evidence/resolve with correct body and returns data", async () => {
    const payload = { claim_id: 1, claim_text: "test", evidences: [], primary_evidence: null, primary_page: null, case_id: 116, report_ref: "r", citation_id: "1" };
    mockFetch.mockResolvedValueOnce({ ok: true, json: async () => payload });
    const { useEvidenceResolve } = await import("@/lib/hooks/use-evidence-resolve");
    const { result } = renderHook(() => useEvidenceResolve());

    await act(async () => {
      await result.current.resolve({ case_id: 116, report_ref: "r", citation_id: "1" });
    });

    expect(mockFetch).toHaveBeenCalledWith(
      "http://test/evidence/resolve",
      expect.objectContaining({ method: "POST" })
    );
    await waitFor(() => expect(result.current.data?.claim_text).toBe("test"));
  });

  it("sets error on non-ok response", async () => {
    mockFetch.mockResolvedValueOnce({ ok: false, status: 404 });
    const { useEvidenceResolve } = await import("@/lib/hooks/use-evidence-resolve");
    const { result } = renderHook(() => useEvidenceResolve());

    await act(async () => {
      await result.current.resolve({ case_id: 1, report_ref: "r", citation_id: "1" }).catch(() => {});
    });

    await waitFor(() => expect(result.current.error).not.toBeNull());
  });
});

describe("usePageAnchors", () => {
  it("fetches page anchors when fileId and pageNo provided", async () => {
    const payload = { file_id: 1, page_no: 3, page_width: 800, page_height: 1100, page_image_ref: "http://img", anchors: [] };
    mockFetch.mockResolvedValueOnce({ ok: true, json: async () => payload });
    const { usePageAnchors } = await import("@/lib/hooks/use-page-anchors");
    const { result } = renderHook(() => usePageAnchors(1, 3));

    await waitFor(() => expect(result.current.data?.page_no).toBe(3));
  });

  it("does not fetch when fileId is null", async () => {
    const { usePageAnchors } = await import("@/lib/hooks/use-page-anchors");
    renderHook(() => usePageAnchors(null, 1));
    expect(mockFetch).not.toHaveBeenCalled();
  });
});
