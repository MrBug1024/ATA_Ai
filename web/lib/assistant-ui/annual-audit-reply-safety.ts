/**
 * Identifies an older drill-down response written before the response-scoped
 * analysis-run contract existed.  It deliberately distinguishes an absent
 * field from an empty array: `responseAnalysisRuns: []` means a newer reply
 * was evaluated and produced no usable run, while `undefined` is legacy data
 * whose auditability cannot be established.
 */
export function isLegacyUnauditableAuditDrilldownReply(value: unknown): boolean {
  if (typeof value !== "object" || value === null || Array.isArray(value)) return false;
  const metadata = value as Record<string, unknown>;

  const routeDecision = metadata.routeDecision;
  if (
    typeof routeDecision !== "object" ||
    routeDecision === null ||
    Array.isArray(routeDecision) ||
    (routeDecision as Record<string, unknown>).capability !== "audit.drilldown"
  ) {
    return false;
  }

  // New replies always carry this property, including the valid empty array.
  if (metadata.responseAnalysisRuns !== undefined) return false;

  const traceItems = metadata.traceItems;
  if (Array.isArray(traceItems) && traceItems.length > 0) return false;

  const coverage = metadata.citationCoverage;
  if (typeof coverage !== "object" || coverage === null || Array.isArray(coverage)) {
    return true;
  }
  const totalClaims = (coverage as Record<string, unknown>).total_claims;
  return typeof totalClaims !== "number" || totalClaims === 0;
}
