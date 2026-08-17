import { beforeEach, describe, expect, it, vi } from "vitest";

const mockFetch = vi.fn();
vi.stubGlobal("fetch", mockFetch);
vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", "http://cs");

beforeEach(() => {
  mockFetch.mockReset();
});

describe("annual-audit execution backend contract", () => {
  it("builds controlled execution and release-gate URLs", async () => {
    const api = await import("@/lib/backend/annual-audit");
    expect(api.annualAuditExecutionKey(41)).toBe("http://cs/api/annual-audit/41/execution");
    expect(api.annualAuditReleaseGateKey(41)).toBe("http://cs/api/annual-audit/41/release-gate");
  });

  it("uses governed endpoints for all mutable project controls", async () => {
    mockFetch.mockResolvedValue({ ok: true, json: async () => ({}) });
    const api = await import("@/lib/backend/annual-audit");

    await api.updateAnnualAuditProfile(41, { acceptance_status: "accepted" });
    await api.updateAnnualAuditProgramItem(41, "F 1/2", { status: "in_progress" });
    await api.recordAnnualAuditReview(41, {
      review_level: "project_manager",
      decision: "approved",
    });
    await api.evaluateAnnualAuditReleaseGate(41);
    await api.freezeAnnualAuditPolicyBinding(41, {
      knowledge_release_id: 7,
      ruleset_id: 9,
    });
    await api.getAnnualAuditPolicyCatalog();

    expect(mockFetch).toHaveBeenNthCalledWith(
      1,
      "http://cs/api/annual-audit/41/profile",
      expect.objectContaining({ method: "PUT" })
    );
    expect(mockFetch).toHaveBeenNthCalledWith(
      2,
      "http://cs/api/annual-audit/41/program/F%201%2F2",
      expect.objectContaining({ method: "PUT" })
    );
    expect(mockFetch).toHaveBeenNthCalledWith(
      3,
      "http://cs/api/annual-audit/41/reviews",
      expect.objectContaining({ method: "POST" })
    );
    expect(mockFetch).toHaveBeenNthCalledWith(
      4,
      "http://cs/api/annual-audit/41/release-gate",
      expect.objectContaining({ method: "POST" })
    );
    expect(mockFetch).toHaveBeenNthCalledWith(
      5,
      "http://cs/api/annual-audit/41/policy-binding",
      expect.objectContaining({ method: "POST" })
    );
    expect(mockFetch).toHaveBeenNthCalledWith(
      6,
      "http://cs/api/annual-audit/knowledge/policy-catalog",
      undefined
    );
  });
});
