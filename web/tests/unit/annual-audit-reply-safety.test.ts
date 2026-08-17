import { describe, expect, it } from "vitest";
import { isLegacyUnauditableAuditDrilldownReply } from "@/lib/assistant-ui/annual-audit-reply-safety";

describe("isLegacyUnauditableAuditDrilldownReply", () => {
  it("flags a legacy drill-down reply with no response evidence snapshot", () => {
    expect(
      isLegacyUnauditableAuditDrilldownReply({
        routeDecision: { capability: "audit.drilldown" },
        traceItems: [],
        citationCoverage: { total_claims: 0, cited_claims: 0 },
      })
    ).toBe(true);
  });

  it("does not flag a new evaluated reply with an explicit empty run list", () => {
    expect(
      isLegacyUnauditableAuditDrilldownReply({
        routeDecision: { capability: "audit.drilldown" },
        traceItems: [],
        citationCoverage: { total_claims: 0, cited_claims: 0 },
        responseAnalysisRuns: [],
      })
    ).toBe(false);
  });

  it("does not flag a drill-down reply that has response-scoped evidence", () => {
    expect(
      isLegacyUnauditableAuditDrilldownReply({
        routeDecision: { capability: "audit.drilldown" },
        traceItems: [{ citation_id: "1" }],
      })
    ).toBe(false);
  });
});
