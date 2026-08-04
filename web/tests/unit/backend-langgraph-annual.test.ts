import { beforeEach, describe, expect, it, vi } from "vitest";

const mockFetch = vi.fn();
vi.stubGlobal("fetch", mockFetch);
vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", "http://annual-api");

beforeEach(() => mockFetch.mockReset());

describe("annual audit backend contract", () => {
  it("uses the single unified backend for chat, evidence, and adjustments", async () => {
    const api = await import("@/lib/backend/langgraph");
    expect(api.threadsKey({ caseId: 7 })).toBe(
      "http://annual-api/chat/threads?case_id=7&limit=50&offset=0"
    );
    expect(api.caseMaterialEventsKey(7)).toBe(
      "http://annual-api/files/cases/7/material-events"
    );
    expect(api.graphEntitiesKey(7)).toBe(
      "http://annual-api/graph/cases/7/entities"
    );
    expect(api.caseCorrectionsKey(7)).toBe(
      "http://annual-api/cases/7/corrections"
    );
  });

  it("lists and writes annual-audit adjustments", async () => {
    mockFetch
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({ case_id: 7, corrections: [{ id: 1 }] }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({ id: 2, status: "active" }),
      });

    const { listCaseCorrections, createCorrection } = await import(
      "@/lib/backend/langgraph"
    );
    expect(await listCaseCorrections(7)).toEqual([{ id: 1 }]);
    await createCorrection(7, {
      target: "收入截止性",
      instruction: "以期后出库单复核结果为准",
    });
    expect(mockFetch.mock.calls[0][0]).toBe(
      "http://annual-api/cases/7/corrections"
    );
    expect(mockFetch.mock.calls[1][0]).toBe(
      "http://annual-api/cases/7/corrections"
    );
  });
});
