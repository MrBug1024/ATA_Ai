import { describe, it, expect, vi, beforeEach } from "vitest";

const mockFetch = vi.fn();
vi.stubGlobal("fetch", mockFetch);
vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", "http://cs");

beforeEach(() => {
  mockFetch.mockReset();
});

describe("key builders", () => {
  it("builds expected URLs", async () => {
    const cs = await import("@/lib/backend/cases");
    expect(cs.casesKey(1, "")).toBe("http://cs/api/cases?page=1&page_size=20");
    expect(cs.casesKey(2, "债")).toBe(
      `http://cs/api/cases?page=2&page_size=20&keyword=${encodeURIComponent("债")}`
    );
    expect(cs.docCategoriesKey()).toBe("http://cs/api/ingest/doc-categories");
    expect(cs.caseDocCategoriesKey(7)).toBe("http://cs/api/case/7/doc-categories");
  });
});

describe("operations", () => {
  it("getDocCategories unwraps categories", async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({ categories: [{ code: "contract" }] }),
    });
    const { getDocCategories } = await import("@/lib/backend/cases");
    expect(await getDocCategories()).toEqual([{ code: "contract" }]);
  });

  it("createCase posts payload and surfaces FastAPI detail errors", async () => {
    mockFetch.mockResolvedValueOnce({
      ok: false,
      status: 422,
      json: async () => ({ detail: [{ msg: "案件名称不能为空" }] }),
    });
    const { createCase } = await import("@/lib/backend/cases");
    const err = await createCase({ case_name: "", case_type: "年度财务报表审计" }).catch(
      (e: unknown) => e
    );
    expect((err as Error).message).toBe("案件名称不能为空");
  });

  it("validateDocCategory posts JSON body", async () => {
    mockFetch.mockResolvedValueOnce({ ok: true, json: async () => ({ ok: true }) });
    const { validateDocCategory } = await import("@/lib/backend/cases");
    await validateDocCategory({ case_id: 7, doc_category: "contract", filename: "a.pdf" });
    expect(mockFetch).toHaveBeenCalledWith(
      "http://cs/api/ingest/validate-doc-category",
      expect.objectContaining({ method: "POST" })
    );
  });
});
